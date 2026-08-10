"""
持仓损益水印 v3
修复：sh/sz 分批复用 + 全部持仓显盈亏
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
    """按交易所分批复用"""
    prices = {}
    sh_codes = [c for c in codes if c.startswith("6")]
    sz_codes = [c for c in codes if not c.startswith("6")]

    for exchange, batch_codes in [("sh", sh_codes), ("sz", sz_codes)]:
        for i in range(0, len(batch_codes), 40):
            batch = batch_codes[i:i+40]
            symbols = ",".join(f"{exchange}{c}" for c in batch)
            try:
                r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
                r.encoding = "gbk"
                for line in r.text.strip().split("\n"):
                    if "=" not in line or '""' in line:
                        continue
                    # 从行中提取代码
                    try:
                        code = line.split("_")[-1].split("=")[0]
                        code = code.replace("sh", "").replace("sz", "")
                        parts = line.split("~")
                        if len(parts) >= 4 and parts[3]:
                            prices[code] = float(parts[3])
                    except:
                        continue
            except Exception as e:
                print(f"  批量取价 {exchange} 失败: {e}")
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
    print(f"[START] 持仓损益 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    cash = hold.get("cash", 0)

    codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(codes)

    positions = []
    total_cost = 0
    total_mv = 0
    zero_cost = []

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
            zero_cost.append((name, mv))
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
            "mv": mv, "price": price, "cost": cost,
        })

    total_asset = total_mv + cash
    total_pnl = total_mv - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    cash_pct = cash / total_asset * 100 if total_asset else 0

    positions.sort(key=lambda x: x["pnl_pct"], reverse=True)
    gainers = [p for p in positions if p["pnl_pct"] >= 0]
    losers = [p for p in positions if p["pnl_pct"] < 0]

    lines = [f"## 💧 持仓损益 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]
    lines.append(f"💰 总市值 {total_mv:,.0f} + 现金 {cash:,.0f} = **{total_asset:,.0f}**")
    lines.append(f"📊 总成本 {total_cost:,.0f} | 浮动盈亏 {total_pnl:+,.0f}（{total_pnl_pct:+.1f}%）")
    lines.append(f"🏦 现金 {cash_pct:.0f}%")
    lines.append("")

    if gainers:
        lines.append("### 📈 浮盈")
        for p in gainers:
            lines.append(f"- **{p['name']}** 市值{p['mv']:,.0f} | {p['pnl_pct']:+.1f}%")
        lines.append("")
    if losers:
        lines.append("### 📉 浮亏")
        for p in losers:
            lines.append(f"- **{p['name']}** 市值{p['mv']:,.0f} | {p['pnl_pct']:.1f}%")
        lines.append("")
    if zero_cost:
        lines.append("### 🏆 零成本")
        for name, mv in zero_cost:
            lines.append(f"- **{name}** 市值{mv:,.0f} | 纯利润")

    push(f"💧 持仓损益 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(gainers)}盈 {len(losers)}亏 总资产{total_asset:,.0f}")


if __name__ == "__main__":
    main()
