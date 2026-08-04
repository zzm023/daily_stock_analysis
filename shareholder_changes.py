#!/usr/bin/env python3
"""大股东增减持周报：东方财富公告接口批量扫描
每周一 08:00 ｜ 扫52只近7天公告，过滤增减持/权益变动关键词
"""
import requests
import os
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

KEYWORDS = ["增持", "减持", "权益变动", "股份变动", "回购"]
ANNO_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_announcements(codes_str, page=1):
    """东财批量拉公告，一次最多50只"""
    params = {
        "sr": -1, "page_size": 50, "page_index": page, "ann_type": "A",
        "client_source": "web", "stock_list": codes_str, "f_node": 0, "s_node": 0,
    }
    r = requests.get(ANNO_URL, params=params, headers=HEADERS, timeout=15)
    return r.json()


def push(title, content):
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] 无TOKEN"); return
    payload = {"token": token, "title": title, "content": content, "template": "markdown"}
    if topic: payload["topic"] = topic
    r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")


def main():
    import time
    now = datetime.now()
    since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"[START] 增减持扫描 {now:%Y-%m-%d %H:%M} | 窗口: 7天")

    hits = []
    codes = [c for c, _ in STOCKS]
    for i in range(0, len(codes), 50):
        batch = ",".join(codes[i:i+50])
        for attempt in range(3):
            try:
                j = fetch_announcements(batch)
                lst = (j.get("data") or {}).get("list") or []
                print(f"  批次{i//50+1}: 拉到 {len(lst)} 条公告")
                for a in lst:
                    date = (a.get("notice_date") or "")[:10]
                    title = a.get("title", "")
                    code = a.get("sec_code", "")
                    if date >= since and any(k in title for k in KEYWORDS):
                        name = a.get("sec_name", "")
                        hits.append((name, code, date, title))
                        print(f"  🔥 {name} {date} {title}")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  批次{i//50+1} 失败,重试..."); time.sleep(5*(attempt+1))
                else:
                    print(f"  批次{i//50+1} 最终失败: {e}")

    lines = [f"## 📢 大股东增减持 — {now:%Y.%m.%d}", "",
             f"> 近7天公告（东方财富）｜ 52只 ｜ 命中 {len(hits)} 条", ""]
    if hits:
        lines.append("| 股票 | 日期 | 公告标题 |")
        lines.append("|------|------|---------|")
        for name, code, d, title in hits:
            lines.append(f"| {name}({code}) | {d} | {title} |")
    else:
        lines.append("本周无增减持/权益变动公告 ✅")
    lines.append("")
    lines.append("> ⚠️ 关键词：增持/减持/权益变动/股份变动/回购。以公告原文为准。")

    push(f"📢 增减持周报 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 命中 {len(hits)} 条")


if __name__ == "__main__":
    main()
