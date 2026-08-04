#!/usr/bin/env python3
import requests
import re
import os
from datetime import datetime

STOCKS = [
    {"code": "600036", "name": "招商银行",  "trigger": 35.00, "attr": "①永续债"},
    {"code": "601601", "name": "中国太保",  "trigger": 30.00, "attr": "①永续债"},
    {"code": "600018", "name": "上港集团",  "trigger": 4.80,  "attr": "①永续债"},
    {"code": "601816", "name": "京沪高铁",  "trigger": 4.80,  "attr": "①永续债"},
    {"code": "600900", "name": "长江电力",  "trigger": None,  "attr": "①永续债", "anchor": "息率≥4%"},
    {"code": "600941", "name": "中国移动",  "trigger": 90.00, "attr": "①永续债"},
    {"code": "600406", "name": "国电南瑞",  "trigger": 20.00, "attr": "①永续债"},
    {"code": "600598", "name": "北大荒",    "trigger": 11.50, "attr": "①永续债"},
    {"code": "603568", "name": "伟明环保",  "trigger": 14.50, "attr": "①永续债候补"},
    {"code": "600007", "name": "中国国贸",  "trigger": 17.50, "attr": "①永续债候补"},
    {"code": "000429", "name": "粤高速A",   "trigger": 10.50, "attr": "①永续债观察"},
    {"code": "000895", "name": "双汇发展",  "trigger": 22.00, "attr": "②高息成长"},
    {"code": "000848", "name": "承德露露",  "trigger": 8.00,  "attr": "②高息成长"},
    {"code": "000157", "name": "中联重科",  "trigger": 7.00,  "attr": "③周期拐点"},
    {"code": "600585", "name": "海螺水泥",  "trigger": None,  "attr": "③周期拐点", "anchor": "PB≤0.55"},
    {"code": "000792", "name": "盐湖股份",  "trigger": 25.00, "attr": "③周期拐点"},
    {"code": "600188", "name": "兖矿能源",  "trigger": 15.50, "attr": "③周期拐点"},
    {"code": "002601", "name": "龙佰集团",  "trigger": 13.50, "attr": "③周期拐点候补"},
    {"code": "600299", "name": "安迪苏",    "trigger": 7.60,  "attr": "③周期拐点候补"},
    {"code": "300498", "name": "温氏股份",  "trigger": None,  "attr": "③周期观察", "anchor": "PB≤1.5"},
    {"code": "000651", "name": "格力电器",  "trigger": 38.00, "attr": "④全球寡头"},
    {"code": "600066", "name": "宇通客车",  "trigger": 27.00, "attr": "④全球寡头"},
    {"code": "000333", "name": "美的集团",  "trigger": 68.00, "attr": "④全球寡头"},
    {"code": "600690", "name": "海尔智家",  "trigger": 20.00, "attr": "④全球寡头"},
    {"code": "600031", "name": "三一重工",  "trigger": 17.00, "attr": "④全球寡头"},
    {"code": "600309", "name": "万华化学",  "trigger": 68.00, "attr": "④全球寡头"},
    {"code": "600660", "name": "福耀玻璃",  "trigger": 50.00, "attr": "④全球寡头"},
    {"code": "600761", "name": "安徽合力",  "trigger": 16.50, "attr": "④全球寡头"},
    {"code": "600486", "name": "扬农化工",  "trigger": 52.00, "attr": "④全球寡头"},
    {"code": "601058", "name": "赛轮轮胎",  "trigger": 12.00, "attr": "④全球寡头"},
    {"code": "603806", "name": "福斯特",    "trigger": 13.50, "attr": "④全球寡头"},
    {"code": "000708", "name": "中信特钢",  "trigger": 13.50, "attr": "④全球寡头候补"},
    {"code": "002027", "name": "分众传媒",  "trigger": 5.26,  "attr": "⑤品牌心智"},
    {"code": "000538", "name": "云南白药",  "trigger": 47.00, "attr": "⑤品牌心智"},
    {"code": "603605", "name": "珀莱雅",    "trigger": 55.00, "attr": "⑤品牌心智"},
    {"code": "605098", "name": "行动教育",  "trigger": 48.00, "attr": "⑤品牌心智"},
    {"code": "600298", "name": "安琪酵母",  "trigger": 35.00, "attr": "⑤品牌心智"},
    {"code": "300628", "name": "亿联网络",  "trigger": 33.00, "attr": "⑤品牌心智"},
    {"code": "002508", "name": "老板电器",  "trigger": 14.05, "attr": "⑤品牌心智"},
    {"code": "002032", "name": "苏泊尔",    "trigger": 40.00, "attr": "⑤品牌心智候补"},
    {"code": "002884", "name": "凌霄泵业",  "trigger": 15.00, "attr": "⑥小众冠军"},
    {"code": "002318", "name": "久立特材",  "trigger": 17.50, "attr": "⑥小众冠军"},
    {"code": "603855", "name": "华荣股份",  "trigger": 15.20, "attr": "⑥小众冠军"},
    {"code": "603288", "name": "海天味业",  "trigger": 30.00, "attr": "⑥小众冠军"},
    {"code": "603508", "name": "思维列控",  "trigger": 21.60, "attr": "⑥小众冠军"},
    {"code": "600161", "name": "天坛生物",  "trigger": 11.50, "attr": "⑥小众冠军候补"},
    {"code": "300832", "name": "新产业",    "trigger": 40.00, "attr": "科技✅⚠"},
    {"code": "688187", "name": "时代电气",  "trigger": 46.00, "attr": "科技✅⚠"},
    {"code": "300124", "name": "汇川技术",  "trigger": 47.00, "attr": "科技观察"},
    {"code": "002837", "name": "英维克",    "trigger": 43.00, "attr": "科技观察"},
    {"code": "300627", "name": "华测导航",  "trigger": 26.50, "attr": "科技观察"},
    {"code": "002410", "name": "广联达",    "trigger": 8.50,  "attr": "科技观察"},
]

ATTR_ORDER={"①永续债":0,"①永续债候补":1,"①永续债观察":2,"②高息成长":3,"③周期拐点":4,"③周期拐点候补":5,"③周期观察":6,"④全球寡头":7,"④全球寡头候补":8,"⑤品牌心智":9,"⑤品牌心智候补":10,"⑥小众冠军":11,"⑥小众冠军候补":12,"科技✅⚠":13,"科技观察":14}
ATTR_LABEL={"①永续债":"🏰 ①永续债","①永续债候补":"🏰 ①候补","①永续债观察":"🏰 ①观察","②高息成长":"💵 ②高息成长","③周期拐点":"🔄 ③周期拐点","③周期拐点候补":"🔄 ③候补","③周期观察":"🔄 ③观察","④全球寡头":"🌍 ④全球寡头","④全球寡头候补":"🌍 ④候补","⑤品牌心智":"🧠 ⑤品牌心智","⑤品牌心智候补":"🧠 ⑤候补","⑥小众冠军":"🏆 ⑥小众冠军","⑥小众冠军候补":"🏆 ⑥候补","科技✅⚠":"⚡ 科技✅⚠","科技观察":"⚡ 科技观察"}


def fetch_all_stocks():
    """腾讯接口：批量获取行情（含PE）"""
    import time
    codes = list(set(s["code"] for s in STOCKS))
    symbols = []
    for code in codes:
        prefix = "sh" if code.startswith("6") else "sz"
        symbols.append(f"{prefix}{code}")

    lookup = {}
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i+50]
        url = "http://qt.gtimg.cn/q=" + ",".join(batch)
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=15)
                resp.encoding = "gbk"
                for line in resp.text.strip().split("\n"):
                    m = re.search(r'v_(\w+)="(.+)"', line)
                    if not m:
                        continue
                    fields = m.group(2).split("~")
                    code = m.group(1)[2:]  # sh600036 -> 600036
                    try:
                        price = float(fields[3]) if fields[3] else 0
                        pe = float(fields[38]) if len(fields)>38 and fields[38] else 0
                        pb = 0  # 腾讯接口暂不提供PB
                        lookup[code] = {"最新价": price, "市盈率-动态": pe, "市净率": pb}
                    except (ValueError, IndexError):
                        pass
                count = sum(1 for s in batch if s[2:] in lookup)
                print(f"  批次{i//50+1}: {count}/{len(batch)}")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  批次{i//50+1} 失败, {10*(attempt+1)}秒后重试...")
                    time.sleep(10*(attempt+1))
                else:
                    print(f"  批次{i//50+1} 最终失败: {e}")
    print(f"  总计获取 {len(lookup)}/52 只")
    return lookup


def build_report(data):
    now = datetime.now()
    lines = [f"## 📊 每周复盘 — {now.strftime('%Y.%m.%d')}", "", f"> PE / 距触发价 ｜ {now.strftime('%m-%d %H:%M')}", ""]
    stocks = sorted(STOCKS, key=lambda s: (ATTR_ORDER.get(s["attr"],99), s["code"]))
    cur, total, hit, close = None, 0, 0, 0
    for s in stocks:
        g = ATTR_LABEL.get(s["attr"], s["attr"])
        if g != cur:
            cur = g
            lines += [f"### {g}", "", "| 股票 | 现价 | PE | 触发价 | 差距% |", "|------|------|-----|--------|-------|"]
        row = data.get(s["code"], {})
        price = row.get("最新价", 0) if row else 0
        pe = row.get("市盈率-动态", 0) if row else 0
        ps = f"{price:.2f}" if price else "-"
        pes = f"{pe:.1f}" if pe else "-"
        trigger = s["trigger"]
        anchor = s.get("anchor", "")
        if trigger and price:
            gap = (price - trigger) / trigger * 100
            if gap <= 0: gs = f"🔴 {gap:+.1f}%"; hit += 1
            elif gap < 10: gs = f"🟡 {gap:+.1f}%"; close += 1
            else: gs = f"⚪ {gap:+.1f}%"
            ts = f"{trigger:.2f}"
        else:
            gs = "-"; ts = anchor if anchor else "-"
        lines.append(f"| {s['name']} | {ps} | {pes} | {ts} | {gs} |")
        total += 1
    lines.insert(4, f"> 🔴已触发:{hit} | 🟡近10%内:{close} | ⚪安全区:{total-hit-close}")
    lines.insert(5, "")
    return "\n".join(lines)


def push(title, content):
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] 无PUSHPLUS_TOKEN"); return
    payload = {"token": token, "title": title, "content": content, "template": "markdown"}
    if topic: payload["topic"] = topic
    r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    print(f"[OK]" if r.json().get("code")==200 else f"[FAIL] {r.json()}")


def main():
    print(f"[START] {datetime.now()}")
    data = fetch_all_stocks()
    report = build_report(data)
    push(f"📊 每周复盘 {datetime.now().strftime('%Y.%m.%d')}", report)
    print("[DONE]")

if __name__ == "__main__":
    main()
