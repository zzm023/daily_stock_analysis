"""
持仓损益水印 v1
每日计算：总盈亏 / 年化估算 / 最大浮盈股 / 最大浮亏股
挂 sell_monitor 同一 workflow
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_prices(codes):
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for line in r.text.strip().split("\n"):
                if "=" not in line or '""' in line:
                    continue
                code = line.split("_")[-1].split("=")[0].replace("sh","").replace("sz","")
                parts = line.split("~")
                if len(parts) >= 4 and parts[3]:
                    prices[code] = float(parts[3])
        except:
            pass
    return prices


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 持仓损益水印 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    total_capital = state.get("meta", {}).get("total_capital", 400000)
    cash = hold.get("cash", 0)

    # 批量取价
    codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(codes)

    positions = []
    total_cost = 0
    total_mv = 0

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)

        if cost < 0:
            price = prices.get(code, 0)
            mv = price * shares if price else 0
            total_mv += mv
            positions.append({"name": name, "pnl_pct": "∞", "pnl_abs": mv, "mv": mv})
            continue

        cb = cost * shares
        total_cost += cb
        price = prices.get(code, 0)
        mv = price * shares if price else cb
        total_mv += mv
        pnl = mv - cb
        pnl_pct = (pnl / cb * 100) if cb else 0
        positions.append({
            "name": name, "pnl_pct": pnl_pct, "pnl_abs": pnl,
            "mv": mv, "cost": cost, "shares": shares,
        })

    total_asset = total_mv + cash
    total_pnl = total_mv - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    cash_pct = cash / total_asset * 100 if total_asset else 0

    # 排序找最大盈亏
    sorted_pnl = sorted([p for p in positions if p["pnl_pct"] != "∞"],
                        key=lambda x: x["pnl_pct"], reverse=True)
    top_gainer = sorted_pnl[0] if sorted_pnl else None
    top_loser = sorted_pnl[-1] if sorted_pnl else None

    lines = [f"## 💧 持仓损益 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    lines.append(f"💰 总市值 {total_mv:,.0f} + 现金 {cash:,.0f} = **{total_asset:,.0f}**")
    lines.append(f"📊 总成本 {total_cost:,.0f} | 浮动盈亏 {total_pnl:+,.0f}（{total_pnl_pct:+.1f}%）")
    lines.append(f"🏦 现金占比 {cash_pct:.0f}%")
    lines.append("")

    if top_gainer:
        lines.append(f"📈 最大浮盈：**{top_gainer['name']}** +{top_gainer['pnl_pct']:.1f}%")
    if top_loser and top_loser["pnl_pct"] < 0:
        lines.append(f"📉 最大浮亏：**{top_loser['name']}** {top_loser['pnl_pct']:.1f}%")
    lines.append("")

    # 持仓盈亏一览
    for p in sorted_pnl[:5] if sorted_pnl else []:
        lines.append(f"- **{p['name']}** 市值{p['mv']:,.0f} | {p['pnl_pct']:+.1f}%")

    push(f"💧 持仓损益 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 总资产{total_asset:,.0f} 盈亏{total_pnl:+,.0f}")


if __name__ == "__main__":
    main()
