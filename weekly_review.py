#!/usr/bin/env python3
"""
每周复盘 v2：PE / PB / 距触发价汇总
联动 framework_state.json：读触发价 → 更新现价
数据源：新浪财经 — 每周六 18:00
"""
import requests
import re
import os
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"

# 全量股票（仅用于属性标注，触发价从状态文件读）
STOCKS = [
    {"code": "600036", "name": "招商银行",  "attr": "①永续债"},
    {"code": "601601", "name": "中国太保",  "attr": "①永续债"},
    {"code": "600018", "name": "上港集团",  "attr": "①永续债"},
    {"code": "601816", "name": "京沪高铁",  "attr": "①永续债"},
    {"code": "600900", "name": "长江电力",  "attr": "①永续债"},
    {"code": "600941", "name": "中国移动",  "attr": "①永续债"},
    {"code": "600406", "name": "国电南瑞",  "attr": "①永续债"},
    {"code": "600598", "name": "北大荒",    "attr": "①永续债"},
    {"code": "603568", "name": "伟明环保",  "attr": "①永续债"},
    {"code": "600007", "name": "中国国贸",  "attr": "①永续债"},
    {"code": "000429", "name": "粤高速A",   "attr": "①永续债"},
    {"code": "000895", "name": "双汇发展",  "attr": "②高息成长"},
    {"code": "000848", "name": "承德露露",  "attr": "②高息成长"},
    {"code": "000157", "name": "中联重科",  "attr": "③周期拐点"},
    {"code": "600585", "name": "海螺水泥",  "attr": "③周期拐点"},
    {"code": "000792", "name": "盐湖股份",  "attr": "③周期拐点"},
    {"code": "600188", "name": "兖矿能源",  "attr": "③周期拐点"},
    {"code": "002601", "name": "龙佰集团",  "attr": "③周期拐点"},
    {"code": "600299", "name": "安迪苏",    "attr": "③周期拐点"},
    {"code": "300498", "name": "温氏股份",  "attr": "③周期拐点"},
    {"code": "000651", "name": "格力电器",  "attr": "④全球寡头"},
    {"code": "600066", "name": "宇通客车",  "attr": "④全球寡头"},
    {"code": "000333", "name": "美的集团",  "attr": "④全球寡头"},
    {"code": "600690", "name": "海尔智家",  "attr": "④全球寡头"},
    {"code": "600031", "name": "三一重工",  "attr": "④全球寡头"},
    {"code": "600309", "name": "万华化学",  "attr": "④全球寡头"},
    {"code": "600660", "name": "福耀玻璃",  "attr": "④全球寡头"},
    {"code": "600761", "name": "安徽合力",  "attr": "④全球寡头"},
    {"code": "600486", "name": "扬农化工",  "attr": "④全球寡头"},
    {"code": "601058", "name": "赛轮轮胎",  "attr": "④全球寡头"},
    {"code": "603806", "name": "福斯特",    "attr": "④全球寡头"},
    {"code": "000708", "name": "中信特钢",  "attr": "④全球寡头"},
    {"code": "002027", "name": "分众传媒",  "attr": "⑤品牌心智"},
    {"code": "000538", "name": "云南白药",  "attr": "⑤品牌心智"},
    {"code": "603605", "name": "珀莱雅",    "attr": "⑤品牌心智"},
    {"code": "605098", "name": "行动教育",  "attr": "⑤品牌心智"},
    {"code": "600298", "name": "安琪酵母",  "attr": "⑤品牌心智"},
    {"code": "300628", "name": "亿联网络",  "attr": "⑤品牌心智"},
    {"code": "002508", "name": "老板电器",  "attr": "⑤品牌心智"},
    {"code": "002032", "name": "苏泊尔",    "attr": "⑤品牌心智"},
    {"code": "002884", "name": "凌霄泵业",  "attr": "⑥小众冠军"},
    {"code": "002318", "name": "久立特材",  "attr": "⑥小众冠军"},
    {"code": "603855", "name": "华荣股份",  "attr": "⑥小众冠军"},
    {"code": "603288", "name": "海天味业",  "attr": "⑥小众冠军"},
    {"code": "603508", "name": "思维列控",  "attr": "⑥小众冠军"},
    {"code": "600161", "name": "天坛生物",  "attr": "⑥小众冠军"},
    {"code": "300832", "name": "新产业",    "attr": "科技✅⚠"},
    {"code": "688187", "name": "时代电气",  "attr": "科技✅⚠"},
    {"code": "300124", "name": "汇川技术",  "attr": "科技✅⚠"},
    {"code": "002837", "name": "英维克",    "attr": "科技✅⚠"},
    {"code": "300627", "name": "华测导航",  "attr": "科技✅⚠"},
    {"code": "002410", "name": "广联达",    "attr": "科技✅⚠"},
]

ATTR_ORDER = {
    "①永续债":0,"②高息成长":1,"③周期拐点":2,"④全球寡头":3,
    "⑤品牌心智":4,"⑥小众冠军":5,"科技✅⚠":6,
}
ATTR_LABEL = {
    "①永续债":"🏰 ①永续债","②高息成长":"💵 ②高息成长",
    "③周期拐点":"🔄 ③周期拐点","④全球寡头":"🌍 ④全球寡头",
    "⑤品牌心智":"🧠 ⑤品牌心智","⑥小众冠军":"🏆 ⑥小众冠军",
    "科技✅⚠":"⚡ 科技",
}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger": {}, "holdings": {}}


def fetch_all_prices():
    codes = list(set(s["code"] for s in STOCKS))
    symbols = []
    for code in codes:
        prefix = "sh" if code.startswith("6") else "sz"
        symbols.append(f"{prefix}{code}")

    lookup = {}
    batch_size = 25
    headers = {"Referer": "https://finance.sina.com.cn"}

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        url = "https://hq.sinajs.cn/list=" + ",".join(batch)
        resp = None
        for retry in range(3):
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                break
            except Exception:
                if retry < 2:
                    time.sleep(3 * (retry + 1))
        if resp is None:
            continue
        try:
            resp.encoding = "gbk"
            for line in resp.text.strip().split("\n"):
                m = re.search(r'hq_str_(\w+)="(.+)"', line)
                if not m:
                    continue
                sym = m.group(1)
                fields = m.group(2).split(",")
                code = sym[2:]
                try:
                    price = float(fields[3]) if fields[3] else 0
                    pe = float(fields[39]) if len(fields)>39 and fields[39] else 0
                    pb = float(fields[42]) if len(fields)>42 and fields[42] else 0
                    lookup[code] = {"price": price, "pe": pe, "pb": pb}
                except (ValueError, IndexError):
                    pass
        except Exception:
            pass

    return lookup


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("[WARN] 无TOKEN"); return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now()
    print(f"[START] 每周复盘 v2 {now:%Y-%m-%d %H:%M}")

    state = load_state()
    trigger = state.get("trigger", {})
    data = fetch_all_prices()

    lines = [f"## 📊 每周复盘 — {now:%Y.%m.%d}", "",
             f"> PE / PB / 距触发价 ｜ {now:%m-%d %H:%M}", ""]

    stocks_sorted = sorted(STOCKS, key=lambda s: (ATTR_ORDER.get(s["attr"],99), s["code"]))
    cur, total, hit, close_10 = None, 0, 0, 0

    for s in stocks_sorted:
        g = ATTR_LABEL.get(s["attr"], s["attr"])
        if g != cur:
            cur = g
            lines.append(f"### {g}")
            lines.append("")

        code = s["code"]
        row = data.get(code, {})
        price = row.get("price", 0)
        pe = row.get("pe", 0)
        pb = row.get("pb", 0)

        # 触发价从状态文件读
        tp = trigger.get(code, {}).get("trigger_price", 0)

        ps = f"{price:.2f}" if price else "-"
        pes = f"{pe:.1f}" if pe else "-"
        pbs = f"{pb:.2f}" if pb else "-"

        if tp and price:
            gap = (price - tp) / tp * 100
            if gap <= 0:
                gs = f"🔴 {gap:+.1f}%"; hit += 1
            elif gap < 10:
                gs = f"🟡 {gap:+.1f}%"; close_10 += 1
            else:
                gs = f"⚪ {gap:+.1f}%"
            ts = f"{tp:.2f}"
        else:
            gs = "-"
            ts = "-"

        lines.append(f"**{s['name']}** {ps} PE{pes} PB{pbs}")
        lines.append(f"> 触发价 {ts} 差距 {gs}")
        lines.append("")
        total += 1

    lines.insert(4, f"> 🔴已触发:{hit} | 🟡近触发(10%):{close_10} | ⚪安全区:{total-hit-close_10}")
    lines.insert(5, "")

    push(f"📊 每周复盘 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {total} 只")


if __name__ == "__main__":
    main()
