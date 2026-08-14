"""
框架状态校准 v5.3 — 只更新DPS，不覆盖触发价
修复：DPS按年度累加（中期+年末）+ 🔻偏高单独提醒
触发价是多重共振锚点，自动化无权改
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def _to_ts(code):
    if "." in code: return code
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("[Push] ❌ 无 PUSHPLUS_TOKEN，跳过推送")
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC: payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
        resp = r.json()
        print(f"[Push] code={resp.get('code')} msg={resp.get('msg')}")
    except Exception as e:
        print(f"[Push] ❌ 异常: {e}")


def tushare_call(api, params, fields):
    ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
    requests.post("https://api.tushare.pro", json={
        "api_name": "ip_whitelist", "token": TOKEN, "params": {"ip": ip}}, timeout=10)
    payload = {"api_name": api, "token": TOKEN, "params": params, "fields": fields}
    r = requests.post("https://api.tushare.pro", json=payload, timeout=30)
    d = r.json()
    if d.get("code") != 0:
        return []
    return d["data"]["items"]


def fetch_eps_latest(codes):
    result = {}
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("fina_indicator", {"ts_code": ts},
                           "ts_code,end_date,eps")
        if not rows:
            continue
        best = None
        best_year = ""
        for row in rows:
            ed = str(int(row[1]))
            val = row[2]
            if not val or not ed.endswith("1231"):
                continue
            year = ed[:4]
            if year > best_year:
                best_year = year
                best = float(val)
        if best and best > 0:
            result[code] = best
        time.sleep(0.15)
    return result


def fetch_dps_map(codes):
    result = {}
    current_year = datetime.now().year
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("dividend", {"ts_code": ts},
                           "ts_code,cash_div,end_date")
        if not rows:
            continue
        year_total = {}
        for row in rows:
            cash_div = row[1]
            ed = str(int(row[2]))
            if not cash_div:
                continue
            val = float(cash_div)
            if val <= 0:
                continue
            year = ed[:4]
            year_total[year] = year_total.get(year, 0) + val
        valid = {y: t for y, t in year_total.items() if int(y) < current_year}
        if valid:
            best_year = max(valid.keys())
            result[code] = round(valid[best_year], 3)
        time.sleep(0.15)
    return result


def main():
    now = datetime.now()
    print(f"[START] 校准 v5.3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    print(f"  触发清单: {len(codes)} 只")

    eps_map = fetch_eps_latest(codes)
    dps_map = fetch_dps_map(codes)
    print(f"  EPS{len(eps_map)}只 DPS{len(dps_map)}只")

    dps_updates = 0
    for code, dps in dps_map.items():
        if code in trigger and dps != trigger[code].get("dps", 0):
            trigger[code]["dps"] = dps
            dps_updates += 1

    drifts = []
    for code in codes:
        t = trigger[code]
        pe_upper = t.get("pe_upper", 0)
        trigger_price = t.get("trigger_price", 0)
        eps = eps_map.get(code)

        if pe_upper > 0 and eps and trigger_price > 0:
            pe_implied_price = round(pe_upper * eps, 2)
            drift_pct = (pe_implied_price - trigger_price) / trigger_price * 100

            if abs(drift_pct) > 5:
                drifts.append({
                    "name": t["name"], "code": code,
                    "trigger": trigger_price,
                    "pe_price": pe_implied_price,
                    "drift": round(drift_pct, 1),
                    "pe": pe_upper, "eps": eps,
                })

    state["meta"]["updated"] = now.isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ── 分离 🔻偏高 / 🔺保守 ──
    high = [d for d in drifts if d["drift"] < 0]   # 触发价 > 隐含价（偏高）
    low = [d for d in drifts if d["drift"] >= 0]   # 触发价 < 隐含价（保守）
    high.sort(key=lambda x: x["drift"])            # 偏高最多的排前
    low.sort(key=lambda x: -x["drift"])            # 保守最多的排前

    lines = [f"## 🔧 校准 {now:%m.%d}", "",
             f"> 仅更新DPS，触发价不动。隐含价=PE上限×EPS（分属性设定）", "",
             f"✅ DPS更新 {dps_updates}只 ｜ ⚠️偏高 {len(high)} ｜ 🔺保守 {len(low)}", ""]

    if high:
        lines.append(f"### ⚠️ 触发价偏高（{len(high)}只，建议复核）")
        lines.append("")
        for d in high[:10]:
            lines.append(f"**{d['name']}** 🔻{abs(d['drift']):.0f}%")
            lines.append(f"> 触发 {d['trigger']:.2f} → 隐含 {d['pe_price']:.2f}（PE{d['pe']}×EPS{d['eps']:.2f}）")
            lines.append("")
        if len(high) > 10:
            lines.append(f"> 其余 {len(high)-10} 只略")
            lines.append("")

    if low:
        lines.append(f"### ✅ 触发价保守（{len(low)}只，正常）")
        lines.append("")
        for d in low[:5]:
            lines.append(f"· {d['name']} 🔺{d['drift']:.0f}%")
            lines.append("")
        if len(low) > 5:
            lines.append(f"> 其余 {len(low)-5} 只略")
            lines.append("")

    push(f"🔧 校准 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] DPS{dps_updates}只 | 偏高{len(high)} 保守{len(low)}")


if __name__ == "__main__":
    main()
