"""
周末汇总周报 v2
修复：接近股票实时价、排版优化
每周日 09:00 CST
"""
import os
import json
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
DATA_FILE = Path(__file__).parent / "market_temperature.json"
COMM_FILE = Path(__file__).parent / "commodity_prices.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
    except:
        pass


def get_price(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) >= 4 and parts[3]:
            return float(parts[3])
    except:
        pass
    return 0


def get_sina_index(sina_code):
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={sina_code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text or '""' in text:
            return None
        data = text.split('"')[1].split(",")
        return {"price": float(data[1]), "chg_pct": float(data[3])} if len(data) >= 4 else None
    except:
        return None


def main():
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=4)
    print(f"[START] 周末汇总周报 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    total_capital = state.get("meta", {}).get("total_capital", 400000)
    cash = hold.get("cash", 0)

    lines = [
        f"## 📋 周末汇总 — {week_start:%m.%d}-{week_end:%m.%d}",
        "",
        f"{now:%H:%M} | {now:%Y.%m.%d}",
        "",
    ]

    # ═══ 1. 持仓 ═══
    lines.append("### 💼 持仓盈亏")
    lines.append("")
    total_mv = 0
    positions = []

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)

        if cost < 0:
            price = get_price(code)
            mv = price * shares if price else 0
            total_mv += mv
            positions.append((name, mv, "∞·零成本"))
            continue

        cb = cost * shares
        price = get_price(code)
        mv = price * shares if price else cb
        total_mv += mv
        pnl_pct = (price - cost) / cost * 100 if cost and price else 0
        pnl_s = f"{pnl_pct:+.1f}%"
        positions.append((name, mv, pnl_s))

    total_asset = total_mv + cash

    for name, mv, pnl in positions:
        lines.append(f"**{name}** | 市值{mv:,.0f} | 盈亏{pnl}")
        lines.append("")
    lines.append(f"💰 总资产{total_asset:,.0f} | 现金{cash:,.0f}（{cash/total_asset*100:.0f}%）")

    # ═══ 2. 触发价 ═══
    approaching = {k: v for k, v in trigger.items() if v.get("status") == "接近"}
    lines.append("")
    lines.append("### 🎯 触发价概览")
    lines.append(f"已触发 0 | 接近 {len(approaching)} | 持仓 {len(positions)}")
    lines.append("")

    if approaching:
        gap_list = []
        for code, v in approaching.items():
            gap = v.get("gap_pct", 99)
            resonance = v.get("resonance", "")
            price = get_price(code)  # 实时价
            target = v.get("trigger_price", 0)
            if price and target:
                gap_list.append((code, v.get("name", code), price, target, gap, resonance))

        gap_list.sort(key=lambda x: x[4])
        for code, name, price, target, gap, resonance in gap_list[:5]:
            r_tag = " ⚡双振" if "双振" in resonance else ""
            lines.append(f"- **{name}** 现{price:.2f} 触发{target:.2f} 差{gap:.1f}%{r_tag}")
        lines.append("")

    # ═══ 3. 卖出 ═══
    lines.append("### 📋 卖出关注")
    has_sell = False
    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        cost = v.get("cost", 0)
        if cost <= 0:
            continue
        price = get_price(code)
        if price and cost and price >= cost * 1.5:
            lines.append(f"**{v.get('name', code)}** 盈亏{((price-cost)/cost*100):+.0f}% — 接近翻倍关注")
            has_sell = True
    if not has_sell:
        lines.append("无。所有持仓距翻倍尚远。")
    lines.append("")

    # ═══ 4. 商品 ═══
    lines.append("### 🛢 大宗商品")
    if COMM_FILE.exists():
        with open(COMM_FILE, "r", encoding="utf-8") as f:
            comm = json.load(f)
        shown = 0
        for name, v in comm.items():
            if v and shown < 6:
                lines.append(f"- {name}: {v['price']:,.0f} {v.get('unit','')}")
                shown += 1
    lines.append("")

    # ═══ 5. 下周关注 ═══
    lines.append("### 👀 下周关注")
    gaps = []
    for code, v in approaching.items():
        g = v.get("gap_pct", 99)
        r = v.get("resonance", "")
        if "双振" in r:
            gaps.append((code, v.get("name", code), g))
    gaps.sort(key=lambda x: x[2])
    if gaps:
        for code, name, g in gaps[:3]:
            lines.append(f"1. **{name}** 距触发{g:.1f}% | 双振确认 — 若到位可分层买入")
    else:
        lines.append("无明确共振标的需要关注。")
    lines.append("")

    lines.append("---")
    lines.append("📌 每周汇总，非操作指令。所有买卖由你决策。")
    push(f"📋 周报 {week_start:%m.%d}-{week_end:%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
