"""
框架状态校准 v1 — Tushare版
每周一跑：重算 PE触发价 / 股息率触发价 / 更新 DPS
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


def fetch_income_map(codes):
    """Tushare income: n_income_attr_p 单位=万元"""
    result = {}
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("income",
            {"ts_code": ts, "end_date": "20261231"},
            "ts_code,end_date,n_income_attr_p")
        if not rows:
            continue
        periods = {}
        for row in rows:
            ed = str(int(row[1]))
            val = row[2]
            if not val:
                continue
            periods[ed] = float(val)
        result[code] = periods
        time.sleep(0.15)
    return result


def fetch_shares(codes):
    """Tushare daily_basic: total_share 单位=万股"""
    result = {}
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("daily_basic",
            {"ts_code": ts, "trade_date": datetime.now().strftime("%Y%m%d")},
            "ts_code,total_share")
        if not rows:
            rows = tushare_call("daily_basic", {"ts_code": ts}, "ts_code,total_share")
        if rows and rows[0][1]:
            result[code] = float(rows[0][1])
        time.sleep(0.15)
    return result


def fetch_dps_map(codes):
    """同一年多条求和"""
    result = {}
    for i, code in enumerate(codes):
        ts = _to_ts(code)
        rows = tushare_call("dividend",
            {"ts_code": ts},
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
    print(f"[START] 校准 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    print(f"  触发清单: {len(codes)} 只")

    # ── 拉数据 ──
    income_map = fetch_income_map(codes)
    shares_map = fetch_shares(codes)
    dps_map = fetch_dps_map(codes)
    print(f"  利润{len(income_map)}只 股本{len(shares_map)}只 DPS{len(dps_map)}只")

    # ── 重算 ──
    changes = []
    for code in codes:
        t = trigger[code]
        old_trigger = t.get("trigger_price", 0)
        new_trigger = None
        reason = ""

        pe_upper = t.get("pe_upper", 0)
        income = income_map.get(code, {})
        shares = shares_map.get(code)

        if pe_upper > 0 and income and shares:
            annual = income.get("20251231")
            if annual:
                # 万元 ÷ 万股 = 元/股（单位正好抵消）
                eps = annual / shares
                if eps > 0:
                    new_trigger = round(pe_upper * eps, 2)
                    reason = f"PE{pe_upper}×EPS{eps:.2f}"

        if new_trigger and new_trigger > 0:
            diff_pct = (new_trigger - old_trigger) / old_trigger * 100 if old_trigger > 0 else 999
            if abs(diff_pct) > 1:
                t["trigger_price"] = new_trigger
                changes.append({
                    "code": code, "name": t["name"],
                    "old": old_trigger, "new": new_trigger,
                    "diff_pct": round(diff_pct, 1), "reason": reason,
                })

        if code in dps_map:
            t["dps"] = dps_map[code]

    # ── 写回 ──
    state["meta"]["updated"] = now.isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ── 推送 ──
    lines = [f"## 🔧 校准 {now:%m.%d}", "",
             f"> PE重算{len(changes)}只 | DPS更新{len(dps_map)}只", ""]
    if changes:
        lines.append("| 股票 | 旧触发价 | 新触发价 | 变动 | 依据 |")
        lines.append("|:--|:--|:--|:--|:--|")
        for c in changes[:20]:
            arrow = "↑" if c["diff_pct"] > 0 else "↓"
            lines.append(f"| {c['name']} | {c['old']:.2f} | {c['new']:.2f} | {arrow}{abs(c['diff_pct']):.1f}% | {c['reason']} |")
        if len(changes) > 20:
            lines.append(f"| ... | | | | +{len(changes)-20}只 |")
    else:
        lines.append("> ✅ 无超过1%的变动")

    push(f"🔧 校准 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] 变更{len(changes)}只 DPS更新{len(dps_map)}只")


if __name__ == "__main__":
    main()
