"""
周末汇总周报 v1
整合：触发价/估值共振/持仓/卖出/仓位/季报/商品/温度
每周日 09:00 CST 推送
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
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


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
    print(f"[START] 周末汇总周报 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    total_capital = state.get("meta", {}).get("total_capital", 400000)
    cash = hold.get("cash", 0)

    lines = [
        f"## 📋 周末汇总周报 — {week_start:%m.%d}-{week_end:%m.%d}",
        "",
        f"{now:%H:%M} | {now:%Y.%m.%d}",
        "",
    ]

    # ═══ 1. 持仓盈亏 ═══
    lines.append("### 💼 持仓盈亏")
    lines.append("")

    total_cost = 0
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
            positions.append((name, cost, mv, "∞"))
            continue

        cb = cost * shares
        total_cost += cb
        price = get_price(code)
        mv = price * shares if price else cb
        total_mv += mv
        pnl_pct = (price - cost) / cost * 100 if cost else 0
        positions.append((name, cost, mv, f"{pnl_pct:+.1f}%"))

    total_asset = total_mv + cash

    for p in positions:
        name, cost, mv, pnl = p
        lines.append(
            f"**{name}** | 市值{mv:,.0f} | 盈亏{pnl}" +
            ("" if cost >= 0 else " | 零成本")
        )
        lines.append("")

    lines.append(f"💰 总资产{total_asset:,.0f} | 现金{cash:,.0f}({cash/total_asset*100:.0f}%) | 市值{total_mv:,.0f}")

    # ═══ 2. 触发价概览 ═══
    triggered = {k: v for k, v in trigger.items() if v.get("status") == "已触发"}
    approaching = {k: v for k, v in trigger.items() if v.get("status") == "接近"}

    lines.append("")
    lines.append("### 🎯 触发价概览")
    lines.append(f"已触发 {len(triggered)} 只 | 接近 {len(approaching)} 只 | 持仓 {len(positions)} 只")
    lines.append("")

    if approaching:
        top = sorted(approaching.items(), key=lambda x: x[1].get("gap_pct", 99))[:5]
        for code, v in top:
            name = v.get("name", code)
            price = v.get("price_now", 0)
            target = v.get("trigger_price", 0)
            gap = v.get("gap_pct", 0)
            resonance = v.get("resonance", "")
            r_tag = "⚡共振" if "双振" in resonance else ""
            lines.append(f"- **{name}** 现{price:.2f} 触发{target:.2f} 差{gap:.1f}% {r_tag}")
        lines.append("")

    # ═══ 3. 卖出信号 ═══
    lines.append("### 📋 卖出关注")
    has_sell = False
    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        cost = v.get("cost", 0)
        if cost < 0:
            continue
        price = get_price(code)
        if price and price >= cost * 1.5:
            lines.append(f"**{v.get('name', code)}** 盈亏{((price-cost)/cost*100):+.0f}% — 接近翻倍关注区")
            has_sell = True
    if not has_sell:
        lines.append("无。所有持仓距翻倍尚远。")
    lines.append("")

    # ═══ 4. 大宗商品快照 ═══
    lines.append("### 🛢 大宗商品快照")
    if COMM_FILE.exists():
        with open(COMM_FILE, "r", encoding="utf-8") as f:
            comm = json.load(f)
        for name, v in comm.items():
            if v:
                lines.append(f"- {name}: {v['price']:,.0f} {v.get('unit','')}")
    lines.append("")

    # ═══ 5. 市场温度 ═══
    lines.append("### 🌡 市场温度")
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            temp = json.load(f)
        for name in ["沪深300", "上证50", "中证500"]:
            h = temp.get(name, [])
            if h:
                last = float(h[-1].split(":")[1])
                lines.append(f"- **{name}** {last:,.0f}")
    lines.append("")

    # ═══ 6. 下周关注 ═══
    lines.append("### 👀 下周关注")
    gaps = []
    for code, v in approaching.items():
        g = v.get("gap_pct", 99)
        r = v.get("resonance", "")
        if "双振" in r:
            gaps.append((code, v.get("name", code), g, r))
    gaps.sort(key=lambda x: x[2])
    if gaps:
        for code, name, g, r in gaps[:3]:
            lines.append(f"1. **{name}** 距触发{g:.1f}% | 双振确认 — 若到位可分层买入")
    lines.append("")

    lines.append("---")
    lines.append("📌 以上为每周汇总，非操作指令。所有买卖由你决策。")

    push(f"📋 周报 {week_start:%m.%d}-{week_end:%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
