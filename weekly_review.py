#!/usr/bin/env python3
"""
每周复盘：52只框架股票 PE / PB / 股息率 / 距触发价 汇总
运行频率：每周五 20:00 CST
数据源：akshare (东方财富实时行情)
推送：PushPlus
"""

import akshare as ak
import requests
import json
import os
import sys
import time
from datetime import datetime

# ============================================================
# 52只框架股票（与 price_monitor.py 保持同步）
# ============================================================
STOCKS = [
    # ── ①永续债 核心底仓 ──
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

    # ── ②高息成长 ──
    {"code": "000895", "name": "双汇发展",  "trigger": 22.00, "attr": "②高息成长"},
    {"code": "000848", "name": "承德露露",  "trigger": 8.00,  "attr": "②高息成长"},

    # ── ③周期拐点 ──
    {"code": "000157", "name": "中联重科",  "trigger": 7.00,  "attr": "③周期拐点"},
    {"code": "600585", "name": "海螺水泥",  "trigger": None,  "attr": "③周期拐点", "anchor": "PB≤0.55"},
    {"code": "000792", "name": "盐湖股份",  "trigger": 25.00, "attr": "③周期拐点"},
    {"code": "600188", "name": "兖矿能源",  "trigger": 15.50, "attr": "③周期拐点"},
    {"code": "002601", "name": "龙佰集团",  "trigger": 13.50, "attr": "③周期拐点候补"},
    {"code": "600299", "name": "安迪苏",    "trigger": 7.60,  "attr": "③周期拐点候补"},
    {"code": "300498", "name": "温氏股份",  "trigger": None,  "attr": "③周期观察", "anchor": "待定"},

    # ── ④全球寡头 ──
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

    # ── ⑤品牌心智 ──
    {"code": "002027", "name": "分众传媒",  "trigger": 5.26,  "attr": "⑤品牌心智"},
    {"code": "000538", "name": "云南白药",  "trigger": 47.00, "attr": "⑤品牌心智"},
    {"code": "603605", "name": "珀莱雅",    "trigger": 55.00, "attr": "⑤品牌心智"},
    {"code": "605098", "name": "行动教育",  "trigger": 48.00, "attr": "⑤品牌心智"},
    {"code": "600298", "name": "安琪酵母",  "trigger": 35.00, "attr": "⑤品牌心智"},
    {"code": "300628", "name": "亿联网络",  "trigger": 33.00, "attr": "⑤品牌心智"},
    {"code": "002508", "name": "老板电器",  "trigger": 14.05, "attr": "⑤品牌心智"},
    {"code": "002032", "name": "苏泊尔",    "trigger": 40.00, "attr": "⑤品牌心智候补"},

    # ── ⑥小众冠军 ──
    {"code": "002884", "name": "凌霄泵业",  "trigger": 15.00, "attr": "⑥小众冠军"},
    {"code": "002318", "name": "久立特材",  "trigger": 17.50, "attr": "⑥小众冠军"},
    {"code": "603855", "name": "华荣股份",  "trigger": 15.20, "attr": "⑥小众冠军"},
    {"code": "603288", "name": "海天味业",  "trigger": 30.00, "attr": "⑥小众冠军"},
    {"code": "603508", "name": "思维列控",  "trigger": 21.60, "attr": "⑥小众冠军"},
    {"code": "600161", "name": "天坛生物",  "trigger": 11.50, "attr": "⑥小众冠军候补"},

    # ── 科技 ✅⚠ ──
    {"code": "300832", "name": "新产业",    "trigger": 40.00, "attr": "科技✅⚠"},
    {"code": "688187", "name": "时代电气",  "trigger": 46.00, "attr": "科技✅⚠"},
    {"code": "300124", "name": "汇川技术",  "trigger": 47.00, "attr": "科技观察"},
    {"code": "002837", "name": "英维克",    "trigger": 43.00, "attr": "科技观察"},
    {"code": "300627", "name": "华测导航",  "trigger": 26.50, "attr": "科技观察"},
    {"code": "002410", "name": "广联达",    "trigger": 8.50,  "attr": "科技观察"},
]

ATTR_ORDER = {
    "①永续债": 0, "①永续债候补": 1, "①永续债观察": 2,
    "②高息成长": 3,
    "③周期拐点": 4, "③周期拐点候补": 5, "③周期观察": 6,
    "④全球寡头": 7, "④全球寡头候补": 8,
    "⑤品牌心智": 9, "⑤品牌心智候补": 10,
    "⑥小众冠军": 11, "⑥小众冠军候补": 12,
    "科技✅⚠": 13, "科技观察": 14,
}

ATTR_LABEL = {
    "①永续债": "🏰 ①永续债", "①永续债候补": "🏰 ①候补", "①永续债观察": "🏰 ①观察",
    "②高息成长": "💵 ②高息成长",
    "③周期拐点": "🔄 ③周期拐点", "③周期拐点候补": "🔄 ③候补", "③周期观察": "🔄 ③观察",
    "④全球寡头": "🌍 ④全球寡头", "④全球寡头候补": "🌍 ④候补",
    "⑤品牌心智": "🧠 ⑤品牌心智", "⑤品牌心智候补": "🧠 ⑤候补",
    "⑥小众冠军": "🏆 ⑥小众冠军", "⑥小众冠军候补": "🏆 ⑥候补",
    "科技✅⚠": "⚡ 科技✅⚠", "科技观察": "⚡ 科技观察",
}


def fetch_all_stocks():
    """批量获取52只股票行情（重试+单只fallback）"""
    # ── 方案A：批量拉取，重试3次 ──
    for attempt in range(3):
        try:
            print(f"  批量拉取 第{attempt+1}次...")
            df = ak.stock_zh_a_spot_em()
            df["代码"] = df["代码"].astype(str)
            lookup = {}
            for _, row in df.iterrows():
                lookup[row["代码"]] = row
            print(f"  批量成功，获取 {len(lookup)} 只")
            return lookup
        except Exception as e:
            print(f"  批量失败: {e}")
            if attempt < 2:
                wait = (attempt + 1) * 15
                print(f"  等待{wait}秒重试...")
                time.sleep(wait)

    # ── 方案B：单只逐个拉取 ──
    print("  切换到单只拉取模式...")
    lookup = {}
    codes = list(set(s["code"] for s in STOCKS))
    for i, code in enumerate(codes):
        try:
            df = ak.stock_zh_a_spot_em()
            df["代码"] = df["代码"].astype(str)
            row = df[df["代码"] == code]
            if not row.empty:
                lookup[code] = row.iloc[0]
            time.sleep(0.5)
        except Exception as e:
            print(f"  {code} 失败: {e}")
        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(codes)}")
    print(f"  单只模式完成，获取 {len(lookup)} 只")
    return lookup


def build_report(all_data):
    """生成周报"""
    now = datetime.now()
    lines = []
    lines.append(f"## 📊 每周复盘 — {now.strftime('%Y.%m.%d')}")
    lines.append("")
    lines.append(f"> PE / PB / 距触发价 ｜ 数据截至 {now.strftime('%m-%d %H:%M')}")
    lines.append("")

    stocks_sorted = sorted(STOCKS, key=lambda s: (ATTR_ORDER.get(s["attr"], 99), s["code"]))

    current_group = None
    total = 0
    hit_count = 0
    close_count = 0

    for s in stocks_sorted:
        group = ATTR_LABEL.get(s["attr"], s["attr"])
        if group != current_group:
            current_group = group
            lines.append(f"### {group}")
            lines.append("")
            lines.append("| 股票 | 现价 | PE | PB | 触发价 | 差距% |")
            lines.append("|------|------|-----|-----|--------|-------|")

        code = s["code"]
        name = s["name"]
        trigger = s["trigger"]
        anchor = s.get("anchor", "")

        row = all_data.get(code, {})

        if row and row.get("最新价"):
            price = float(row["最新价"])
            pe = float(row.get("市盈率-动态", 0)) or 0
            pb = float(row.get("市净率", 0)) or 0
        else:
            price = 0
            pe = 0
            pb = 0

        price_str = f"{price:.2f}" if price else "-"
        pe_str = f"{pe:.1f}" if pe else "-"
        pb_str = f"{pb:.2f}" if pb else "-"

        if trigger and price > 0:
            trigger_str = f"{trigger:.2f}"
            gap = (price - trigger) / trigger * 100
            if gap <= 0:
                gap_str = f"🔴 {gap:+.1f}%"; hit_count += 1
            elif gap < 10:
                gap_str = f"🟡 {gap:+.1f}%"; close_count += 1
            else:
                gap_str = f"⚪ {gap:+.1f}%"
        else:
            trigger_str = anchor if anchor else "-"
            gap_str = "-"

        lines.append(f"| {name} | {price_str} | {pe_str} | {pb_str} | {trigger_str} | {gap_str} |")
        total += 1

    summary = f"> 🔴 已触发: {hit_count} 只 | 🟡 近触发(10%内): {close_count} 只 | ⚪ 安全区: {total - hit_count - close_count} 只"
    lines.insert(4, summary)
    lines.insert(5, "")

    return "\n".join(lines)


def send_pushplus(content, title=None):
    """推送至PushPlus"""
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] PUSHPLUS_TOKEN 未设置，仅打印不推送")
        print(content)
        return

    url = "http://www.pushplus.plus/send"
    payload = {
        "token": token,
        "title": title or f"📊 每周复盘 {datetime.now().strftime('%Y.%m.%d')}",
        "content": content,
        "template": "markdown",
    }
    if topic:
        payload["topic"] = topic

    try:
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if data.get("code") == 200:
            print(f"[OK] PushPlus 推送成功")
        else:
            print(f"[ERROR] PushPlus 推送失败: {data}")
    except Exception as e:
        print(f"[ERROR] PushPlus 请求失败: {e}")


def main():
    print(f"[START] 每周复盘 {datetime.now().isoformat()}")
    print("[STEP1] 获取52只股票行情...")
    all_data = fetch_all_stocks()
    print(f"  获取到 {len(all_data)} 只股票行情")
    print("[STEP2] 生成周报...")
    report = build_report(all_data)
    print("[STEP3] 推送 PushPlus...")
    send_pushplus(report)
    print("[DONE]")


if __name__ == "__main__":
    main()
