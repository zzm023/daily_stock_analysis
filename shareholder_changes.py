#!/usr/bin/env python3
"""增减持+质押+解禁监控：只扫标题关键词（砍正文PDF下载）
每周一 08:30 CST ｜ 数据源：东财公告API
"""
import requests
import json
import os
import re
from datetime import datetime, timedelta

STOCKS = [
    ("600036","招商银行"),("601601","中国太保"),("600018","上港集团"),("601816","京沪高铁"),
    ("600900","长江电力"),("600941","中国移动"),("600406","国电南瑞"),("600598","北大荒"),
    ("603568","伟明环保"),("600007","中国国贸"),("000429","粤高速A"),("000895","双汇发展"),
    ("000848","承德露露"),("000157","中联重科"),("600585","海螺水泥"),("000792","盐湖股份"),
    ("600188","兖矿能源"),("002601","龙佰集团"),("600299","安迪苏"),("300498","温氏股份"),
    ("000651","格力电器"),("600066","宇通客车"),("000333","美的集团"),("600690","海尔智家"),
    ("600031","三一重工"),("600309","万华化学"),("600660","福耀玻璃"),("600761","安徽合力"),
    ("600486","扬农化工"),("601058","赛轮轮胎"),("603806","福斯特"),("000708","中信特钢"),
    ("002027","分众传媒"),("000538","云南白药"),("603605","珀莱雅"),("605098","行动教育"),
    ("600298","安琪酵母"),("300628","亿联网络"),("002508","老板电器"),("002032","苏泊尔"),
    ("002884","凌霄泵业"),("002318","久立特材"),("603855","华荣股份"),("603288","海天味业"),
    ("603508","思维列控"),("600161","天坛生物"),("300832","新产业"),("688187","时代电气"),
    ("300124","汇川技术"),("002837","英维克"),("300627","华测导航"),("002410","广联达"),
]

# 标题关键词（命中才下载PDF）
KEYWORDS = [
    "减持", "增持", "质押", "解禁", "解除质押", "补充质押",
    "大宗交易", "协议转让", "权益变动", "简式权益变动",
    "要约收购", "集中竞价", "可交债", "EB换股",
]
# 标题噪声（命中关键词也跳过）
NOISE_TITLE = [
    "激励", "授予", "回购注销", "回购实施", "关联交易",
    "担保", "理财产品", "募集资金", "闲置资金",
]


def fetch_anns(code):
    """东财公告API：近7天"""
    now = datetime.now()
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    all_rows = []
    for page in range(1, 6):
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "sr": "-1", "page_size": "50", "page_index": str(page),
            "ann_type": "A", "client_source": "web",
            "stock_list": code, "f_node": "0", "s_node": "0",
            "begin_time": start, "end_time": end,
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            d = r.json()
            data = d.get("data", {}).get("list", []) or d.get("data", [])
            if not data:
                break
            all_rows.extend(data)
            if len(data) < 50:
                break
        except Exception as e:
            print(f"  {code} 第{page}页失败: {e}")
            break
    return all_rows


def fetch_text(art_code):
    """东财公告PDF文本"""
    try:
        r = requests.get(
            f"https://np-anotice-stock.eastmoney.com/api/security/ann/detail",
            params={"art_code": str(art_code)},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15
        )
        return r.text or ""
    except Exception:
        return ""


def clean(text):
    """清洗HTML标签"""
    return re.sub(r'<[^>]+>', ' ', str(text).replace("&nbsp;", " "))


def extract_summary(text, title=""):
    """提取：股东/数量/比例/方式"""
    raw = clean(text)
    # 找数字+%（最多的两段）
    pcts = re.findall(r'(\d+\.?\d{0,2})\s*%', raw)
    shares = re.findall(r'([\d,]+\.?\d{0,2})\s*[万万千]?股', raw)
    ratios = re.findall(r'(?:占|比例|减持|增持).*?(\d+\.?\d{0,2})\s*%', raw)
    pct = pcts[0] if pcts else (ratios[0] if ratios else None)
    share = shares[0] if shares else None

    if not pct and not share:
        return None

    parts = []
    if share:
        parts.append(f"{share}股")
    if pct:
        parts.append(f"{pct}%")
    # 判断类型
    t = "减持" if any(k in raw for k in ["减持","拟减持","减持计划"]) else ""
    t = "增持" if any(k in raw for k in ["增持","拟增持","增持计划"]) else t
    t = "质押" if any(k in raw for k in ["质押","补充质押"]) else t
    t = "解禁" if any(k in raw for k in ["解禁","上市流通"]) else t
    t = t or "权益变动"
    return f"{t} {'/'.join(parts)}"


def push(title, content):
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] 无TOKEN"); return
    payload = {"token": token, "title": title, "content": content, "template": "markdown"}
    if topic:
        payload["topic"] = topic
    r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")


def main():
    now = datetime.now()
    print(f"[START] 增减持监控 {now:%Y-%m-%d %H:%M}")

    hits = []
    for code, name in STOCKS:
        anns = fetch_anns(code)
        if not anns:
            continue
        for a in anns:
            title = str(a.get("notice_title", ""))
            title_upper = title.upper()
            # 噪声跳过
            if any(k in title_upper for k in ("激励".upper(), "授予".upper(), "回购注销".upper(),
                                               "回购实施".upper(), "理财产品".upper(), "闲置资金".upper())):
                continue
            # 关键词匹配
            if not any(k in title for k in KEYWORDS):
                continue
            art_code = a.get("art_code", "")
            notice_date = str(a.get("notice_date", ""))[:10]
            text = fetch_text(art_code)
            if not text:
                continue
            summary = extract_summary(text, title)
            if summary:
                print(f"  🔥 {name} {notice_date} → {summary}")
                hits.append({"name": name, "code": code, "date": notice_date,
                             "title": title, "summary": summary})
        if anns:
            print(f"  {name}: {len(anns)}条 / {len(hits)}命中")

    if not hits:
        print("[INFO] 近7天无相关公告")
        push(f"📢 增减持 {now:%Y.%m.%d}", "近7天无增减持/质押/解禁相关公告。")
        return

    hits.sort(key=lambda x: x["date"], reverse=True)
    lines = [f"## 📢 增减持+质押+解禁 — {now:%Y.%m.%d}", "",
             f"> 近7天 ｜ 标题关键词命中 ｜ {now:%m-%d %H:%M}", f"> 共{len(hits)}条", ""]

    for h in hits:
        lines.append(f"### {h['name']}({h['code']}) ｜ {h['date']}")
        lines.append(f"**{h['title']}**")
        lines.append(f"> {h['summary']}")
        lines.append("")

    push(f"📢 增减持 {now:%Y.%m.%d}（{len(hits)}条）", "\n".join(lines))
    print(f"[DONE] {len(hits)}条命中")


if __name__ == "__main__":
    main()
