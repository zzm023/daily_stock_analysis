"""
财报日历 + 半年报分析 v2
联动触发清单：只分析已触发/接近触发的股票
数据源：akshare｜ 写事件到 framework_state.json
每周一 08:30，季报/年报期
"""
import akshare as ak
import os
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"

# 全量股票（属性用于标注）——只在已触发清单里的才实际分析
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


def to_float(v):
    if v is None: return None
    s = str(v).replace(",","").replace("%","").replace("元","").replace("亿","").replace("万","").strip()
    try: return float(s)
    except ValueError: return None


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger":{}, "holdings":{}}


def save_state(s):
    s["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def fetch_yjkb(report_date):
    try:
        df = ak.stock_yjkb_em(date=report_date)
        if df is None or df.empty: return {}
        out = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码","")).zfill(6)
            if code not in CODE2NAME: continue
            out[code] = {
                "rev": to_float(r.get("营业收入-营业收入")),
                "rev_g": to_float(r.get("营业收入-同比增长")),
                "profit": to_float(r.get("净利润-净利润")),
                "profit_g": to_float(r.get("净利润-同比增长")),
                "roe": to_float(r.get("净资产收益率")),
                "gm": None,
                "date": str(r.get("公告日期",""))[:10],
            }
        return out
    except Exception as e:
        print(f"  快报失败: {e}"); return {}


def fetch_yjbb(report_date):
    try:
        df = ak.stock_yjbb_em(date=report_date)
        if df is None or df.empty: return {}
        out = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码","")).zfill(6)
            if code not in CODE2NAME: continue
            out[code] = {
                "rev": to_float(r.get("营业总收入-营业总收入")),
                "rev_g": to_float(r.get("营业总收入-同比增长")),
                "profit": to_float(r.get("净利润-净利润")),
                "profit_g": to_float(r.get("净利润-同比增长")),
                "roe": to_float(r.get("净资产收益率")),
                "gm": to_float(r.get("销售毛利率")),
                "date": str(r.get("最新公告日期",""))[:10],
            }
        return out
    except Exception as e:
        print(f"  报表失败: {e}"); return {}


def fetch_kf(code):
    try:
        df = ak.stock_financial_abstract(symbol=code)
        if df is None or df.empty: return None, None
        row = df[df["指标"]=="扣非净利润"]
        if row.empty: return None, None
        cols = list(df.columns)
        cur_col = next((c for c in cols if str(c)=="20260630"), None)
        ly_col = next((c for c in cols if str(c)=="20250630"), None)
        cur = to_float(row.iloc[0].get(cur_col)) if cur_col else None
        ly = to_float(row.iloc[0].get(ly_col)) if ly_col else None
        if cur is not None and ly not in (None,0):
            return cur, (cur-ly)/abs(ly)*100
        return cur, None
    except Exception as e:
        print(f"  {code} 扣非失败: {e}"); return None, None


def yi(v):
    return v/1e8 if v is not None else None


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC: payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def analyze_quality(attr, rev_g, profit_g, kf_g):
    """定性判断"""
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


def main():
    now = datetime.now()
    print(f"[START] 财报日历 v2 {now:%Y-%m-%d %H:%M}")

    state = load_state()
    trigger = state.get("trigger", {})

    # ── 只分析已触发/接近触发的股票 ──
    active_codes = {c for c, v in trigger.items() if v.get("status") in ("已触发","接近")}
    print(f"  触发清单: {len(active_codes)} 只 → {[CODE2NAME.get(c,c) for c in active_codes]}")

    if not active_codes:
        print("[INFO] 无触发清单股票，跳过")
        return

    yjkb = fetch_yjkb("20260630")
    yjbb = fetch_yjbb("20260630")
    ly = fetch_yjbb("20250630")

    data = {}
    for code in active_codes:
        if code in yjkb and code in yjbb:
            yjkb[code]["gm"] = yjbb[code]["gm"]
            data[code] = yjkb[code]
        elif code in yjkb:
            data[code] = yjkb[code]
        elif code in yjbb:
            data[code] = yjbb[code]

    for code in list(data.keys()):
        kf, kf_g = fetch_kf(code)
        data[code]["kf"] = kf
        data[code]["kf_g"] = kf_g

    reported, no_info = [], []
    for code in active_codes:
        name = CODE2NAME.get(code, code)
        attr = CODE2ATTR.get(code, "?")
        if code in data:
            reported.append((code, name, attr, data[code], ly.get(code,{})))
        else:
            no_info.append((code, name, attr))

    # ── 写事件到状态文件 ──
    earnings_events = []
    for code, name, attr, y, l in reported:
        kf_g = y.get("kf_g")
        profit_g = kf_g if kf_g is not None else y.get("profit_g")
        rev_g = y.get("rev_g")
        judgment = analyze_quality(attr, rev_g, profit_g, profit_g)

        event = {
            "type": "财报",
            "code": code,
            "name": name,
            "attr": ATTR_LABEL.get(attr, attr),
            "date": y.get("date", ""),
            "rev_gy": yi(y["rev"]), "rev_g": rev_g,
            "profit_gy": yi(y["profit"]), "profit_g": profit_g,
            "roe": y.get("roe"), "gm": y.get("gm"),
            "judgment": judgment
        }
        earnings_events.append(event)

    state["earnings_events"] = earnings_events
    save_state(state)

    # ── 块状输出 ──
    lines = [f"## 📅 财报联动 — {now:%Y.%m.%d}", "",
             f"> 只分析触发清单 ｜ 已披露{len(reported)}只 ｜ 待披露{len(no_info)}只", ""]

    if reported:
        lines.append("### 📊 已披露")
        lines.append("")
        for code, name, attr, y, l in reported:
            rev = f"{yi(y['rev']):.1f}亿" if y["rev"] is not None else "-"
            rev_g = f"{y['rev_g']:+.1f}%" if y["rev_g"] is not None else "-"
            pf = f"{yi(y['profit']):.1f}亿" if y["profit"] is not None else "-"
            pf_g = f"{y['profit_g']:+.1f}%" if y["profit_g"] is not None else "-"
            kf = f"{yi(y.get('kf')):.1f}亿" if y.get("kf") is not None else "-"
            kf_g = f"{y.get('kf_g'):+.1f}%" if y.get("kf_g") is not None else "-"
            roe = f"{y['roe']:.1f}%" if y["roe"] is not None else "-"
            gm = f"{y['gm']:.1f}%" if y["gm"] is not None else "-"
            attr_name = ATTR_LABEL.get(attr, attr)
            judgment = analyze_quality(attr, y["rev_g"], kf_g if kf_g is not None else y.get("profit_g"), kf_g)

            lines.append(f"**{name}** [{attr_name}] {rev_g} {pf_g} | {judgment}")
            lines.append(f"> 营收{rev} 净利{pf} 扣非{kf} | ROE{roe} 毛利率{gm}")
            lines.append("")

    if no_info:
        lines.append("### ⏳ 待披露")
        for code, name, attr in no_info:
            lines.append(f"- {name} [{ATTR_LABEL.get(attr, attr)}]")
        lines.append("")

    lines.append(f"---")
    lines.append(f"{now:%Y-%m-%d %H:%M} | 触发清单联动")

    push(f"📅 财报监控 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 已披露 {len(reported)} 待披露 {len(no_info)}")


if __name__ == "__main__":
    main()
