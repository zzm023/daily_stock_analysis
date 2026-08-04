#!/usr/bin/env python3
"""财报日历 + 半年报财务数据提取分析
数据源：东财数据中心API直连（含扣非）｜ 每周一 08:30
"""
import requests
import os
from datetime import datetime, timedelta

STOCKS = [
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
CODE2NAME = {c: n for c, n, _ in STOCKS}
CODE2ATTR = {c: a for c, _, a in STOCKS}
ATTR_LABEL = {"①": "永续债", "②": "高息", "③": "周期", "④": "寡头", "⑤": "品牌", "⑥": "小众", "⚡": "科技"}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def fetch_report(report_date):
    """东财业绩报表：营收/净利/扣非/ROE/毛利率+同比"""
    out = {}
    try:
        for page in range(1, 6):
            params = {
                "reportName": "RPT_LICO_FN_CPD",
                "columns": "ALL",
                "filter": f"(REPORTDATE='{report_date[:4]}-{report_date[4:6]}-{report_date[6:]})",
                "pageNumber": str(page),
                "pageSize": "500",
                "sortTypes": "-1",
                "sortColumns": "NOTICE_DATE",
            }
            r = requests.get(DC_URL, params=params, headers=HEADERS, timeout=20)
            j = r.json()
            if not j.get("success"):
                print(f"  {report_date} API返回失败: {str(j)[:200]}")
                break
            rows = (j.get("result") or {}).get("data") or []
            print(f"  {report_date} 第{page}页: {len(rows)}行")
            for row in rows:
                code = str(row.get("SECURITY_CODE", "")).zfill(6)
                if code not in CODE2NAME:
                    continue
                out[code] = {
                    "rev": row.get("TOTAL_OPERATE_INCOME"),
                    "rev_g": row.get("YSTZ"),
                    "profit": row.get("PARENT_NETPROFIT"),
                    "profit_g": row.get("SJLTZ"),
                    "kf": row.get("KCFJCXSYJLR"),
                    "kf_g": row.get("KCFJCXSYJLR_TB"),
                    "roe": row.get("ROEJQ"),
                    "gm": row.get("XSMLL"),
                    "date": str(row.get("NOTICE_DATE", ""))[:10],
                }
            if len(rows) < 500:
                break
    except Exception as e:
        print(f"  {report_date} 数据中心API异常: {e}")
    return out


def fetch_schedule():
    try:
        import akshare as ak
        df = ak.stock_report_disclosure()
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"  披露日程失败: {e}")
    return None


def fetch_yjyg(report_date):
    try:
        import akshare as ak
        df = ak.stock_yjyg_em(date=report_date)
        if df is None or df.empty:
            return {}
        out = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).zfill(6)
            if code in CODE2NAME and code not in out:
                out[code] = f"{r.get('预告类型','')} {r.get('净利润变动幅度','')}"
        return out
    except Exception as e:
        print(f"  业绩预告失败: {e}")
        return {}


def analyze(attr, rev_g, profit_g):
    if profit_g is None:
        return "-"
    if attr == "③":
        if profit_g > 0 and rev_g and rev_g > 0:
            return "🔄 量利齐升·拐点信号"
        if profit_g > 0:
            return "🔄 净利转正"
        return "⏳ 周期底部"
    if attr == "①":
        if profit_g < -10:
            return "⚠️ 盈利下滑"
        return "✅ 稳定"
    if rev_g and profit_g < -10 and rev_g > 5:
        return "⚠️ 增收不增利"
    if profit_g > 20:
        return "🟢 高增长"
    if profit_g < -20:
        return "🔴 大幅下滑"
    return "🟢 增长" if profit_g >= 0 else "🟡 小幅下滑"


def push(title, content):
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] 无TOKEN"); return
    payload = {"token": token, "title": title, "content": content, "template": "markdown"}
    if topic: payload["topic"] = topic
    r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")


def yi(v):
    return v / 1e8 if v is not None else None


def main():
    now = datetime.now()
    today = now.date()
    print(f"[START] 财报日历+业绩分析 {now:%Y-%m-%d %H:%M}")

    sched = {}
    df = fetch_schedule()
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).zfill(6)
            if code not in CODE2NAME:
                continue
            d = r.get("实际披露日期") or r.get("首次预约")
            if d is not None and str(d).strip():
                sched[code] = str(d)[:10]
    print(f"  披露日程 {len(sched)}/52")

    data = fetch_report("20260630")
    ly = fetch_report("20250630")
    print(f"  本期 {len(data)} 只 ｜ 去年同期 {len(ly)} 只")

    yjyg = fetch_yjyg("20260630")
    print(f"  业绩预告 {len(yjyg)} 只")

    reported, upcoming = [], []
    for code, name, attr in STOCKS:
        d = sched.get(code, "")
        if code in data:
            reported.append((code, name, attr, data[code], ly.get(code, {})))
        elif d:
            try:
                dd = datetime.strptime(d, "%Y-%m-%d").date()
                if today <= dd <= today + timedelta(days=30):
                    upcoming.append((dd, code, name, d, yjyg.get(code, "-")))
            except ValueError:
                pass
    upcoming.sort()
    reported.sort(key=lambda x: x[3].get("date", ""))

    lines = [f"## 📅 财报日历+半年报分析 — {now:%Y.%m.%d}", "",
             f"> 已披露 {len(reported)} 只 ｜ 未来30天披露 {len(upcoming)} 只", ""]

    if reported:
        lines.append("### 📊 已披露半年报｜成长")
        lines.append("| 股票 | 营收(亿) | 营收同比 | 净利(亿) | 净利同比 | 扣非(亿) | 扣非同比 |")
        lines.append("|------|---------|---------|---------|---------|---------|---------|")
        for code, name, attr, y, l in reported:
            rev = f"{yi(y['rev']):.1f}" if y["rev"] is not None else "-"
            rev_g = f"{y['rev_g']:+.1f}%" if y["rev_g"] is not None else "-"
            pf = f"{yi(y['profit']):.1f}" if y["profit"] is not None else "-"
            pf_g = f"{y['profit_g']:+.1f}%" if y["profit_g"] is not None else "-"
            kf = f"{yi(y['kf']):.1f}" if y["kf"] is not None else "-"
            kf_g = f"{y['kf_g']:+.1f}%" if y["kf_g"] is not None else "-"
            lines.append(f"| {name} | {rev} | {rev_g} | {pf} | {pf_g} | {kf} | {kf_g} |")
        lines.append("")
        lines.append("### 📊 已披露半年报｜质量+简析")
        lines.append("| 股票 | ROE | ROE同比 | 毛利率 | 毛利率同比 | 简析 |")
        lines.append("|------|-----|---------|--------|-----------|------|")
        for code, name, attr, y, l in reported:
            roe = f"{y['roe']:.1f}%" if y["roe"] is not None else "-"
            gm = f"{y['gm']:.1f}%" if y["gm"] is not None else "-"
            roe_g = f"{y['roe'] - l['roe']:+.1f}pp" if (y["roe"] is not None and l.get("roe") is not None) else "-"
            gm_g = f"{y['gm'] - l['gm']:+.1f}pp" if (y["gm"] is not None and l.get("gm") is not None) else "-"
            a = analyze(CODE2ATTR[code], y["rev_g"], y["kf_g"] if y["kf_g"] is not None else y["profit_g"])
            lines.append(f"| {name} | {roe} | {roe_g} | {gm} | {gm_g} | {a} |")
        lines.append("")

    if upcoming:
        lines.append("### ⏳ 未来30天披露")
        for dd, code, name, d, yg in upcoming:
            lines.append(f"- {dd} {name}：{yg}")
        lines.append("")

    if not reported and not upcoming:
        lines.append("半年报季刚开始，暂无已披露/近期披露（下周继续跟）")

    push(f"📅 财报日历+业绩分析 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 已披露 {len(reported)}，近期 {len(upcoming)}")


if __name__ == "__main__":
    main()
