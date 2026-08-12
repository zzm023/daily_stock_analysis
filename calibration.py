"""
框架状态校准 v3 — Tushare fina_indicator EPS + 3年保守折价
触发价 = min(最新EPS, 3年均EPS) × PE上限
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
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC: payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    except: pass


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


def fetch_eps_3yr(codes):
    """
    返回 {code: {"latest": eps_latest, "avg3": eps_3yr_avg}}
    攒3年年报 2023/2024/2025，至少要2年数据
    """
    result = {}
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("fina_indicator", {"ts_code": ts},
                           "ts_code,end_date,eps")
        if not rows:
            continue
        annual = {}
        for row in rows:
            ed = str(int(row[1]))
            val = row[2]
            if not val or not ed.endswith("1231"):
                continue
            year = int(ed[:4])
            annual[year] = float(val)

        years = sorted(annual.keys())
        if not years:
            continue

        latest = annual[years[-1]]

        # 取最近3年
        recent_3 = [annual[y] for y in years[-3:] if y in annual]
        if len(recent_3) >= 2:
            avg3 = sum(recent_3) / len(recent_3)
        else:
            avg3 = latest

        result[code] = {"latest": latest, "avg3": round(avg3, 2)}
        time.sleep(0.15)
    return result


def fetch_dps_map(codes):
    result = {}
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
            if not cash_div or not ed.endswith("1231"):
                continue
            val = float(cash_div)
            if val <= 0:
                continue
            year = ed[:4]
            year_total[year] = year_total.get(year, 0) + val
        if year_total:
            best_year = max(year_total.keys())
            result[code] = round(year_total[best_year], 3)
        time.sleep(0.15)
    return result


def main():
    now = datetime.now()
    print(f"[START] 校准 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    print(f"  触发清单: {len(codes)} 只")

    eps_3yr = fetch_eps_3yr(codes)
    dps_map = fetch_dps_map(codes)
    print(f"  EPS{len(eps_3yr)}只(含3年均值) DPS{len(dps_map)}只")

    changes = []
    for code in codes:
        t = trigger[code]
        old_trigger = t.get("trigger_price", 0)
        pe_upper = t.get("pe_upper", 0)
        e = eps_3yr.get(code)
        if not e or pe_upper == 0:
            continue

        # 保守折价：取 min(最新, 3年均)
        eps_use = min(e["latest"], e["avg3"])
        new_trigger = round(pe_upper * eps_use, 2)

        diff_pct = (new_trigger - old_trigger) / old_trigger * 100 if old_trigger > 0 else 999
        if abs(diff_pct) > 1:
            t["trigger_price"] = new_trigger
            changes.append({
                "code": code, "name": t["name"],
                "old": old_trigger, "new": new_trigger,
                "diff_pct": round(diff_pct, 1),
                "eps_latest": e["latest"], "eps_avg": e["avg3"],
                "eps_use": eps_use, "pe": pe_upper,
            })

        if code in dps_map:
            t["dps"] = dps_map[code]

    state["meta"]["updated"] = now.isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # 推送
    lines = [f"## 🔧 校准 v3 {now:%m.%d}", "",
             f"> EPS(3年均) {len(eps_3yr)}只 | DPS {len(dps_map)}只", "",
             "**触发价 = min(最新EPS, 3年均EPS) × PE上限**", ""]
    if changes:
        lines.append("| 股票 | 旧→新 | PE | 最新/3年均EPS |")
        lines.append("|:--|:--|:--|:--|")
        for c in changes[:15]:
            arrow = "↑" if c["diff_pct"] > 0 else "↓"
            lines.append(f"| {c['name']} | {c['old']:.2f}→{c['new']:.2f} {arrow}{abs(c['diff_pct']):.0f}% | {c['pe']} | {c['eps_latest']:.2f}/{c['eps_avg']:.2f}→用{c['eps_use']:.2f} |")
        if len(changes) > 15:
            lines.append(f"| ... | +{len(changes)-15}只 | | |")

    push(f"🔧 校准v3 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] 变更{len(changes)}只 DPS更新{len(dps_map)}只")


if __name__ == "__main__":
    main()
