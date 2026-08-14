"""
框架状态校准 v5.5 — 只更新DPS，不覆盖触发价
修复：DPS按年度累加 + PE/PB双隐含价（取更保守的一根）
触发价是多重共振锚点，自动化无权改
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

CRITICAL = 50.0  # 🔥重点阈值：偏离≥50%（触发价≥2倍隐含价）


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


def fetch_financials(codes):
    """拿最新年报 EPS + BPS（每股净资产）"""
    result = {}
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("fina_indicator", {"ts_code": ts},
                           "ts_code,end_date,eps,bps")
        if not rows:
            continue
        best = {}
        best_year = ""
        for row in rows:
            ed = str(int(row[1]))
            if not ed.endswith("1231"):
                continue
            year = ed[:4]
            if year > best_year:
                best_year = year
                try:
                    eps_f = float(row[2]) if row[2] else 0.0
                except:
                    eps_f = 0.0
                try:
                    bps_f = float(row[3]) if row[3] else 0.0
                except:
                    bps_f = 0.0
                best = {"eps": eps_f, "bps": bps_f}
        if best:
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
    print(f"[START] 校准 v5.5 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    print(f"  触发清单: {len(codes)} 只")

    fin_map = fetch_financials(codes)
    dps_map = fetch_dps_map(codes)
    print(f"  财务{len(fin_map)}只 DPS{len(dps_map)}只")

    dps_updates = 0
    for code, dps in dps_map.items():
        if code in trigger and dps != trigger[code].get("dps", 0):
            trigger[code]["dps"] = dps
            dps_updates += 1

    drifts = []
    for code in codes:
        t = trigger[code]
        pe_upper = t.get("pe_upper", 0)
        pb_lower = t.get("pb_lower", 0)
        trigger_price = t.get("trigger_price", 0)
        fin = fin_map.get(code)
        if not fin or trigger_price <= 0:
            continue

        eps = fin.get("eps", 0)
        bps = fin.get("bps", 0)

        pe_implied = pe_upper * eps if (pe_upper > 0 and eps > 0) else None
        pb_implied = pb_lower * bps if (pb_lower > 0 and bps > 0) else None

        implieds = [x for x in [pe_implied, pb_implied] if x is not None and x > 0]
        if not implieds:
            continue
        key_implied = round(min(implieds), 2)  # 取更保守的一根

        drift = (key_implied - trigger_price) / trigger_price * 100

        if abs(drift) > 5:
            drifts.append({
                "name": t["name"], "code": code,
                "trigger": trigger_price,
                "implied": key_implied,
                "drift": round(drift, 1),
                "pe_implied": round(pe_implied, 2) if pe_implied else None,
                "pb_implied": round(pb_implied, 2) if pb_implied else None,
                "pe": pe_upper, "eps": eps,
                "pb": pb_lower, "bps": bps,
            })

    state["meta"]["updated"] = now.isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ── 分三档（隐含价取 PE/PB 更保守者）──
    high = [d for d in drifts if d["drift"] < 0]
    low = [d for d in drifts if d["drift"] >= 0]
    high.sort(key=lambda x: x["drift"])
    low.sort(key=lambda x: -x["drift"])

    critical = [d for d in high if abs(d["drift"]) >= CRITICAL]
    warn = [d for d in high if abs(d["drift"]) < CRITICAL]

    lines = [f"## 🔧 校准 {now:%m.%d}", "",
             f"> 仅更新DPS，触发价不动。隐含价=PE/PB双锚（取更保守）", "",
             f"✅ DPS更新 {dps_updates}只 ｜ 🔥重点 {len(critical)} ｜ ⚠️偏高 {len(warn)} ｜ 🔺保守 {len(low)}", ""]

    if critical:
        lines.append(f"### 🔥 重点复核（触发价≥2倍隐含价，{len(critical)}只）")
        lines.append("")
        for d in critical[:10]:
            lines.append(f"**{d['name']}** 🔻{abs(d['drift']):.0f}%")
            parts = []
            if d["pe_implied"]:
                parts.append(f"PE{d['pe']}×{d['eps']:.2f}={d['pe_implied']:.2f}")
            if d["pb_implied"]:
                parts.append(f"PB{d['pb']}×{d['bps']:.2f}={d['pb_implied']:.2f}")
            lines.append(f"> 触发 {d['trigger']:.2f} → 隐含 {d['implied']:.2f}（{' / '.join(parts)}）")
            lines.append("")
        if len(critical) > 10:
            lines.append(f"> 其余 {len(critical)-10} 只略")
            lines.append("")

    if warn:
        lines.append(f"### ⚠️ 触发价偏高（{len(warn)}只）")
        lines.append("")
        for d in warn[:8]:
            lines.append(f"· {d['name']} 🔻{abs(d['drift']):.0f}%")
            lines.append("")
        if len(warn) > 8:
            lines.append(f"> 其余 {len(warn)-8} 只略")
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
    print(f"[DONE] DPS{dps_updates}只 | 🔥{len(critical)} ⚠️{len(warn)} 🔺{len(low)}")


if __name__ == "__main__":
    main()
