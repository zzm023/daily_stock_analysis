#!/usr/bin/env python3
"""大股东增减持周报：巨潮资讯公告扫描
每周一 08:00 ｜ 扫52只近7天公告，过滤增减持/权益变动关键词
"""
import requests
import json
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

# 增减持相关关键词
KEYWORDS = ["增持", "减持", "权益变动", "股份变动", "回购"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://www.cninfo.com.cn/",
}
SEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
ANNO_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"


def get_org_id(code):
    """获取巨潮内部orgId"""
    try:
        r = requests.get(SEARCH_URL, params={"keyWord": code, "maxNum": 5}, headers=HEADERS, timeout=10)
        for item in r.json():
            if item.get("code") == code:
                return item.get("orgId")
    except Exception as e:
        print(f"  {code} 搜索orgId失败: {e}")
    return None


def get_announcements(code, org_id, since_ts):
    """查询公告列表，返回(时间,标题)列表"""
    data = {
        "pageNum": 1, "pageSize": 30, "column": "szse", "tabName": "fulltext",
        "plate": "", "stock": f"{code},{org_id}", "searchkey": "", "secid": "",
        "category": "", "trade": "", "sealDate": "", "sortName": "", "sortType": "",
        "isHLtitle": "true",
    }
    try:
        r = requests.post(ANNO_URL, data=data, headers=HEADERS, timeout=10)
        j = r.json()
        out = []
        for a in j.get("announcements") or []:
            ts = a.get("announcementTime", 0) / 1000
            if ts >= since_ts:
                out.append((ts, a.get("announcementTitle", "")))
        return out
    except Exception as e:
        print(f"  {code} 公告查询失败: {e}")
        return []


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
    since = now - timedelta(days=7)
    since_ts = since.timestamp()
    print(f"[START] 增减持扫描 {now:%Y-%m-%d %H:%M} | 窗口: {since:%m-%d}~{now:%m-%d}")

    hits = []
    for i, (code, name) in enumerate(STOCKS):
        org = get_org_id(code)
        if not org:
            print(f"  {i+1}/52 {name} orgId失败")
            continue
        anns = get_announcements(code, org, since_ts)
        for ts, title in anns:
            if any(k in title for k in KEYWORDS):
                hits.append((name, code, datetime.fromtimestamp(ts).strftime("%m-%d"), title))
                print(f"  🔥 {name} {datetime.fromtimestamp(ts):%m-%d} {title}")
        if (i+1) % 10 == 0:
            print(f"  进度 {i+1}/52")
        time.sleep(0.2)

    lines = [f"## 📢 大股东增减持 — {now:%Y.%m.%d}", "",
             f"> 近7天公告扫描（巨潮资讯）｜ 52只 ｜ 命中 {len(hits)} 条", ""]
    if hits:
        lines.append("| 股票 | 日期 | 公告标题 |")
        lines.append("|------|------|---------|")
        for name, code, d, title in hits:
            lines.append(f"| {name}({code}) | {d} | {title} |")
    else:
        lines.append("本周无增减持/权益变动公告 ✅")
    lines.append("")
    lines.append(f"> ⚠️ 关键词：增持/减持/权益变动/股份变动/回购。详情以巨潮原文为准。")

    push(f"📢 增减持周报 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 命中 {len(hits)} 条")


if __name__ == "__main__":
    main()
