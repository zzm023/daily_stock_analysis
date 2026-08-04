#!/usr/bin/env python3
"""股息率周报：价格走腾讯 + DPS分红表硬算（东财/乐咕在GitHub Actions被墙）
每周五 20:00 推送 ｜ DPS以2024年报为基准，除权后人工更新
"""
import requests
import re
import os
from datetime import datetime

# ========== 框架防守锚（①永续债/②高息成长 + 特殊锚） ==========
# DPS = 每股分红（元，含中期分红）；anchor = 股息率锚（%）
# ⚠️ 标"待确认"的请按你实际掌握的分红数据更新
DIV = {
     "600036": {"name": "招商银行", "dps": 2.10, "anchor": 6.0},   # 框架息6%+ → 买点35.00=触发价
    "601601": {"name": "中国太保", "dps": 1.02, "anchor": 3.4},   # 非股息锚定(PE/P-EV驱动) 待确认DPS
    "600018": {"name": "上港集团", "dps": 0.18, "anchor": 3.8},   # 待确认DPS
    "601816": {"name": "京沪高铁", "dps": 0.12, "anchor": 2.5},   # 非股息锚定(永续经营驱动)
    "600900": {"name": "长江电力", "dps": 0.85, "anchor": 4.0},   # 锚:息率≥4% → 买点21.25
    "600941": {"name": "中国移动", "dps": 5.35, "anchor": 5.5},   # 锚:息率≥5.5% → 买点97.27(触发价90更严)
    "600406": {"name": "国电南瑞", "dps": 0.25, "anchor": 1.3},   # 非股息锚定(电网垄断驱动)
    "600598": {"name": "北大荒",   "dps": 0.44, "anchor": 3.8},   # 待确认DPS
    "603568": {"name": "伟明环保", "dps": 0.50, "anchor": 3.4},   # 待确认DPS
    "600007": {"name": "中国国贸", "dps": 0.98, "anchor": 5.6},   # 框架息5.6% → 买点17.50=触发价
    "000429": {"name": "粤高速A",  "dps": 0.61, "anchor": 5.8},   # 框架息5.8% → 买点10.52=触发价
    "000895": {"name": "双汇发展", "dps": 1.32, "anchor": 6.0},   # 框架息6% → 买点22.00=触发价
    "000848": {"name": "承德露露", "dps": 0.44, "anchor": 5.5},   # 框架息5.5% → 买点8.00=触发价
}


def get_prices(codes):
    """腾讯批量拉价格，秒回"""
    symbols = []
    for c in codes:
        p = "sh" if c.startswith("6") else "sz"
        symbols.append(f"{p}{c}")
    out = {}
    for i in range(0, len(symbols), 50):
        url = "http://qt.gtimg.cn/q=" + ",".join(symbols[i:i+50])
        try:
            resp = requests.get(url, timeout=15)
            resp.encoding = "gbk"
            for line in resp.text.strip().split("\n"):
                m = re.search(r'v_(\w+)="(.+)"', line)
                if m:
                    f = m.group(2).split("~")
                    try:
                        out[m.group(1)[2:]] = float(f[3])
                    except:
                        pass
        except Exception as e:
            print(f"价格批次失败: {e}")
    return out


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
    print(f"[START] {datetime.now()}")
    codes = list(DIV.keys())
    prices = get_prices(codes)
    now = datetime.now()

    lines = [f"## 💰 股息率周报 — {now.strftime('%Y.%m.%d')}", "",
             f"> 股息率 = DPS ÷ 现价 ｜ 锚为买入触发线 ｜ {now.strftime('%m-%d %H:%M')}", ""]
    alarm, rows = [], []
    for c, d in DIV.items():
        price = prices.get(c, 0)
        if not price:
            rows.append((d["name"], None, d["anchor"], "-", "价格未获取"))
            continue
        yield_pct = d["dps"] / price * 100
        buy_price = d["dps"] / (d["anchor"] / 100)  # 锚对应的买入价
        rows.append((d["name"], yield_pct, d["anchor"], price, buy_price))
        if yield_pct < d["anchor"]:
            alarm.append((d["name"], yield_pct, d["anchor"], buy_price))

    lines.append("### 🚨 未达防守锚（买点未到）")
    if alarm:
        for n, y, a, bp in alarm:
            lines.append(f"- **{n}** 现息 {y:.1f}% < 锚 {a:.0f}% ｜ 需跌至 ≤{bp:.2f}")
    else:
        lines.append("- 全部达标 ✅")
    lines.append("")
    lines.append("| 股票 | 现价 | 股息率 | 防守锚 | 买点价 | 状态 |")
    lines.append("|------|------|--------|--------|--------|------|")
    for n, y, a, price, bp in rows:
        if y is None:
            lines.append(f"| {n} | - | - | {a}% | - | ⚠️ 未获取 |")
        else:
            st = "✅" if y >= a else "🔴"
            lines.append(f"| {n} | {price:.2f} | {y:.1f}% | {a:.0f}% | {bp:.2f} | {st} |")

    push(f"💰 股息率周报 {now.strftime('%Y.%m.%d')}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
