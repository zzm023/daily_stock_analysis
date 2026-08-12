"""
财报日历 v3 — Tushare版
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
TOKEN = os.environ.get("TUSHARE_TOKEN", "")

ALL_STOCKS = [
    ("600036","招商银行","①"),("601601","中国太保","①"),("600018","上港集团","①"),("601816","京沪高铁","①"),
    ("600900","长江电力","①"),("600941","中国移动","①"),("600406","国电南瑞","①"),("600598","北大荒","①"),
    ("603568","伟明环保","①"),("600007","中国国贸","①"),("000429","粤高速A","①"),("000895","双汇发展","②"),
    ("000848","承德露露","②"),("000157","中联重科","③"),("600585","海螺水泥","③"),("000792","盐湖股份","③"),
    ("600188","兖矿能源","③"),("002601","龙佰集团","③"),("600299","安迪苏","③"),("300498","温氏股份","③"),
    ("000651","格力电器","④"),("600066","宇通客车","④"),("000333","美的集团","④"),("600690","海尔智家","④"),
    ("600031","三一重工","④"),("600309","万华化学","④"),("600660","福耀玻璃","④"),("600761","安徽合力","④"),
    ("600486","扬农化工","④"),("601058","赛轮轮胎","④"),("603806","福斯特","④"),("000708","中信特钢","④"),
    ("002027","分众传媒","⑤"),("000538","云南白药","⑤"),("603605","珀莱雅","⑤"),("605098","行动教育","⑤"),
    ("600298","安琪酵母","⑤"),("300628","亿联网络","⑤"),("002508","老板电器","⑤"),("002032","苏泊尔","⑤"),
    ("002884","凌霄泵业","⑥"),("002318","久立特材","⑥"),("603855","华荣股份","⑥"),("603288","海天味业","⑥"),
    ("603508","思维列控","⑥"),("600161","天坛生物","⑥"),("300832","新产业","⚡"),("688187","时代电气","⚡"),
    ("300124","汇川技术","⚡"),("002837","英维克","⚡"),("300627","华测导航","⚡"),("002410","广联达","⚡"),
]
CODE2NAME = {c: n for c, n, _ in ALL_STOCKS}
CODE2ATTR = {c: a for c, _, a in ALL_STOCKS}
ATTR_LABEL = {"①":"永续债","②":"高息","③":"周期","④":"寡头","⑤":"品牌","⑥":"小众","⚡":"科技"}
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def _to_ts_code(code):
    if "." in code: return code
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger": {}, "holdings": {}, "meta": {"updated": ""}}


def save_state(s):
    s["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def yi(v): return v / 1e8 if v is not None else None


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC: payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    except: pass


def analyze_quality(attr, rev_g, profit_g):
    if profit_g is None: return "-"
    if attr == "③":
        if profit_g > 0 and rev_g and rev_g > 0: return "🔄 量利齐升·拐点"
        if profit_g > 0: return "🔄 净利转正"
        return "⏳ 周期底部"
    if attr == "①":
        if profit_g < -10: return "⚠️ 盈利下滑"
        return "✅ 稳定"
    if rev_g and profit_g < -10 and rev_g > 5: return "⚠️ 增收不增利"
    if profit_g > 20: return "🟢 高增长"
    if profit_g < -20: return "🔴 大幅下滑"
    return "🟢 增长" if profit_g >= 0 else "🟡 小幅下滑"


def fetch_earnings(codes):
    """逐只调用 Tushare income，取 2025H1 vs 2024H1"""
    ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
    requests.post("https://api.tushare.pro", json={
        "api_name": "ip_whitelist", "token": TOKEN, "params": {"ip": ip}}, timeout=10)

    cur_period = {}
    prev_period = {}

    for i, code in enumerate(codes):
        ts = _to_ts_code(code)
        payload = {
            "api_name": "income",
            "token": TOKEN,
            "params": {"ts_code": ts, "end_date": "20251231"},
            "fields": "ts_code,end_date,total_revenue,n_income_attr_p",
        }
        try:
            r = requests.post("https://api.tushare.pro", json=payload, timeout=30)
            d = r.json()
            if d.get("code") != 0:
                continue
            rows = d["data"]["items"]
            for row in rows:
                ed = str(int(row[1]))
                rev = float(row[2]) if row[2] else None
                profit = float(row[3]) if row[3] else None
                if ed == "20250630":
                    cur_period[code] = (rev, profit)
                elif ed == "20240630":
                    prev_period[code] = (rev, profit)
        except Exception as e:
            print(f"    {code} FAIL: {e}")
        time.sleep(0.2)

    print(f"  → 2025H1: {len(cur_period)} codes, 2024H1: {len(prev_period)} codes")

    result = {}
    for code in codes:
        if code not in cur_period:
            continue
        rev, profit = cur_period[code]
        prev_rev, prev_profit = prev_period.get(code, (None, None))
        rev_g = ((rev - prev_rev) / abs(prev_rev) * 100) if rev and prev_rev and prev_rev != 0 else None
        profit_g = ((profit - prev_profit) / abs(prev_profit) * 100) if profit and prev_profit and prev_profit != 0 else None
        result[code] = {
            "rev": rev, "rev_g": rev_g,
            "profit": profit, "profit_g": profit_g,
            "roe": None, "gm": None, "date": "",
        }
    return result


def main():
    now = datetime.now()
    print(f"[START] 财报日历 v3 {now:%Y-%m-%d}")
    state = load_state()
    trigger = state.get("trigger", {})
    active_codes = {c for c, v in trigger.items() if v.get("status") in ("已触发", "接近")}
    print(f"  触发清单: {len(active_codes)} 只")

    if not active_codes:
        print("[INFO] 无触发清单股票，跳过")
        return

    data = fetch_earnings(active_codes)
    print(f"  Tushare 半年报 {len(data)} 只")

    reported = [(c, CODE2NAME.get(c, c), CODE2ATTR.get(c, "?"), data[c]) for c in data]
    no_info = [(c, CODE2NAME.get(c, c), CODE2ATTR.get(c, "?")) for c in active_codes if c not in data]

    # 写事件到 state
    earnings_events = []
    for code, name, attr, y in reported:
        judgment = analyze_quality(attr, y.get("rev_g"), y.get("profit_g"))
        earnings_events.append({
            "type": "财报", "code": code, "name": name,
            "attr": ATTR_LABEL.get(attr, attr),
            "rev_gy": yi(y["rev"]), "rev_g": y["rev_g"],
            "profit_gy": yi(y["profit"]), "profit_g": y["profit_g"],
            "judgment": judgment,
        })
    state["earnings_events"] = earnings_events
    save_state(state)

    # 推送
    lines = [f"## 📅 财报联动 — {now:%Y.%m.%d}", "",
             f"> 触发清单 | 已披露{len(reported)}只 | 待披露{len(no_info)}只", ""]
    if reported:
        lines.append("### 📊 已披露（2025H1 vs 2024H1）\n")
        for code, name, attr, y in reported:
            rev = f"{yi(y['rev']):.1f}亿" if y["rev"] is not None else "-"
            rev_g = f"{y['rev_g']:+.1f}%" if y["rev_g"] is not None else "-"
            pf = f"{yi(y['profit']):.1f}亿" if y["profit"] is not None else "-"
            pf_g = f"{y['profit_g']:+.1f}%" if y["profit_g"] is not None else "-"
            judgment = analyze_quality(attr, y["rev_g"], y["profit_g"])
            lines.append(f"**{name}** [{ATTR_LABEL.get(attr, attr)}] {rev_g} {pf_g} | {judgment}")
            lines.append(f"> 营收{rev} 净利{pf}\n")
    if no_info:
        lines.append("### ⏳ 待披露\n")
        for code, name, attr in no_info:
            lines.append(f"- {name} [{ATTR_LABEL.get(attr, attr)}]")
        lines.append("")
    lines.append(f"> Tushare | {now:%m.%d %H:%M}")
    push(f"📅 财报监控 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
