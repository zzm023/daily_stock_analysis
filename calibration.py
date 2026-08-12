"""
框架状态校准 v2 — Tushare fina_indicator EPS
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


def fetch_eps_map(codes):
    """fina_indicator: 拿最新年报 EPS"""
    result = {}
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("fina_indicator", {"ts_code": ts},
                           "ts_code,end_date,eps")
        if not rows:
            continue
        best_eps = None
        best_year = ""
        for row in rows:
            ed = str(int(row[1]))
            eps_val = row[2]
            if not eps_val or not ed.endswith("1231"):
                continue
            year = ed[:4]
            if year > best_year:
                best_year = year
                best_eps = float(eps_val)
        if best_eps and best_eps > 0:
            result[code] = best_eps
        time.sleep(0.15)
    return result


def fetch_dps_map(codes):
    """dividend: 同一年多条求和"""
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
    print(f"[START] 校准 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    print(f"  触发清单: {len(codes)} 只")

    eps_map = fetch_eps_map(codes)
    dps_map = fetch_dps_map(codes)
    print(f"  EPS{len(eps_map)}只 DPS{len(dps_map)}只")

    changes = []
    for code in codes:
        t = trigger[code]
        old_trigger = t.get("trigger_price", 0)
        pe_upper = t.get("pe_upper", 0)
        es = eps_map.get(code)

        if pe_upper > 0 and es:
            new_trigger = round(pe_upper * es, 2)
            diff_pct = (new_trigger - old_trigger) / old_trigger * 100 if old_trigger > 0 else 999

            if abs(diff_pct) > 1:
                t["trigger_price"] = new_trigger
                changes.append({
                    "code": code, "name": t["name"],
                    "old": old_trigger, "new": new_trigger,
                    "diff_pct": round(diff_pct, 1),
                    "eps": es, "pe": pe_upper,
                })

        if code in dps_map:
            t["dps"] = dps_map[code]

    state["meta"]["updated"] = now.isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    lines = [f"## 🔧 校准 {now:%m.%d}", "",
             f"> PE重算{len(changes)}只 | DPS更新{len(dps_map)}只", ""]
    if changes:
        lines.append("| 股票 | 旧→新 | PE | EPS |")
        lines.append("|:--|:--|:--|:--|")
        for c in changes[:15]:
            arrow = "↑" if c["diff_pct"] > 0 else "↓"
            lines.append(f"| {c['name']} | {c['old']:.2f}→{c['new']:.2f} {arrow}{abs(c['diff_pct']):.0f}% | {c['pe']} | {c['eps']:.2f} |")
        if len(changes) > 15:
            lines.append(f"| ... | +{len(changes)-15}只 | | |")

    push(f"🔧 校准 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] 变更{len(changes)}只 DPS更新{len(dps_map)}只")


if __name__ == "__main__":
    main()
