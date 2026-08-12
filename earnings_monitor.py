"""
财报日历 + 半年报分析 v3 — Tushare版
联动触发清单：只分析已触发/接近触发的股票
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"

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


def _from_ts_code(ts_code):
    return ts_code.split(".")[0]


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger": {}, "holdings": {}, "meta": {"updated": ""}}


def save_state(s):
    s["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def yi(v):
    return v / 1e8 if v is not None else None


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC: payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
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
    """
    Tushare: 取最新半年报(20250630 vs 20240630)
    返回 {code: {rev, rev_g, profit, profit_g, roe, gm, date}}
    """
    from tushare_data import _call, auto_whitelist
    auto_whitelist()

    ts_codes = [_to_ts_code(c) for c in codes]

    # 拉所有期间
    all_rows = []
    for i in range(0, len(ts_codes), 10):
        batch = ts_codes[i:i + 10]
        rows = _call("income", {
            "ts_code": ",".join(batch),
            "end_date": "20251231",
        }, "ts_code,end_date,total_revenue,n_income_attr_p")
        all_rows.extend(rows)
        time.sleep(0.3)

    # 按期间分组
    cur_period = {}
    prev_period = {}
    for row in all_rows:
        code = _from_ts_code(row[0])
        ed = str(int(row[1]))
        rev = float(row[2]) if row[2] else None
        profit = float(row[3]) if row[3] else None
        if ed == "20250630":
            cur_period[code] = (rev, profit)
        elif ed == "20240630":
            prev_period[code] = (rev, profit)

    # ROE 从 fina_indicator
    roe_map = {}
    try:
        for i in range(0, len(ts_codes), 10):
            batch = ts_codes[i:i + 10]
            rows = _call("fina_indicator", {
                "ts_code": ",".join(batch),
            }, "ts_code,end_date,roe")
            for row in rows:
                code = _from_ts_code(row[0])
                ed = str(int(row[2])) if row[2] else ""
                if ed.startswith("2025") and row[1]:
                    roe_map[code] = float(row[1])
            time.sleep(0.3)
    except:
        pass

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
            "roe": roe_map.get(code),
            "gm": None,
            "date": "",
        }

    return result


def fetch_forecasts(codes):
    """业绩预告补充"""
    from tushare_data import _call, auto_whitelist
    auto_whitelist()

    ts_codes = [_to_ts_code(c) for c in codes]
    result = {}
    for i in range(0, len(ts_codes), 10):
        batch = ts_codes[i:i + 10]
        try:
            rows = _call("forecast", {
                "ts_code": ",".join(batch),
                "period": "20260630",
            }, "ts_code,type,p_change_min,p_change_max,notice_date")
            for row in rows:
                code = _from_ts_code(row[0])
                result[code] = {
                    "type": row[1],
                    "p_change_min": float(row[2]) if row[2] else None,
                    "p_change_max": float(row[3]) if row[3] else None,
                    "notice_date": row[4],
                }
        except:
            pass
        time.sleep(0.3)
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
    forecasts = fetch_forecasts(active_codes)
    print(f"  Tushare 半年报 {len(data)} 只, 预告 {len(forecasts)} 只")

    reported, no_info = [], []
    for code in active_codes:
        name = CODE2NAME.get(code, code)
        attr = CODE2ATTR.get(code, "?")
        if code in data:
            reported.append((code, name, attr, data[code], forecasts.get(code)))
        else:
            no_info.append((code, name, attr))

    # 写事件
    earnings_events = []
    for code, name, attr, y, fc in reported:
        profit_g = y.get("profit_g")
        rev_g = y.get("rev_g")
        judgment = analyze_quality(attr, rev_g, profit_g)
        event = {
            "type": "财报", "code": code, "name": name,
            "attr": ATTR_LABEL.get(attr, attr),
            "date": fc.get("notice_date", "") if fc else "",
            "rev_gy": yi(y["rev"]), "rev_g": rev_g,
            "profit_gy": yi(y["profit"]), "profit_g": profit_g,
            "roe": y.get("roe"), "gm": y.get("gm"),
            "judgment": judgment,
            "forecast": fc,
        }
        earnings_events.append(event)

    state["earnings_events"] = earnings_events
    save_state(state)

    # 输出
    lines = [f"## 📅 财报联动 — {now:%Y.%m.%d}", "",
             f"> 触发清单 ｜ 已披露{len(reported)}只 ｜ 待披露{len(no_info)}只", ""]

    if reported:
        lines.append("### 📊 已披露（2025H1 vs 2024H1）")
        lines.append("")
        for code, name, attr, y, fc in reported:
            rev = f"{yi(y['rev']):.1f}亿" if y["rev"] is not None else "-"
            rev_g = f"{y['rev_g']:+.1f}%" if y["rev_g"] is not None else "-"
            pf = f"{yi(y['profit']):.1f}亿" if y["profit"] is not None else "-"
            pf_g = f"{y['profit_g']:+.1f}%" if y["profit_g"] is not None else "-"
            roe = f"{y['roe']:.1f}%" if y["roe"] is not None else "-"
            judgment = analyze_quality(attr, y["rev_g"], y["profit_g"])

            fc_tag = ""
            if fc:
                fc_type = fc.get("type", "")
                fc_tag = f"预告:{fc_type}" if fc_type else ""

            lines.append(f"**{name}** [{ATTR_LABEL.get(attr, attr)}] {rev_g} {pf_g} | {judgment} {fc_tag}")
            lines.append(f"> 营收{rev} 净利{pf} | ROE{roe}")
            lines.append("")

    if no_info:
        lines.append("### ⏳ 待披露")
        for code, name, attr in no_info:
            lines.append(f"- {name} [{ATTR_LABEL.get(attr, attr)}]")
        lines.append("")

    lines.append(f"---")
    lines.append(f"> Tushare | {now:%m.%d %H:%M}")

    push(f"📅 财报监控 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 已披露 {len(reported)} 待披露 {len(no_info)}")


if __name__ == "__main__":
    main()
