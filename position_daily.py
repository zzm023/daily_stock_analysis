"""
持仓日报：每天早上推送持仓盈亏、距卖出目标、现金收益
每日 08:30 CST
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_price(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        resp = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=5)
        resp.encoding = "gbk"
        parts = resp.text.split("~")
        if len(parts) >= 4:
            return float(parts[3])
    except:
        pass
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if not row.empty:
            return float(row.iloc[0]["最新价"])
    except:
        pass
    return 0


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now()
    print(f"[START] 持仓日报 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    cash = hold.pop("cash", 0)
    trigger = state.get("trigger", {})
    total_capital = state.get("meta", {}).get("total_capital", 400000)

    total_pnl_total = state.get("meta", {}).get("total_pnl", 0)

    lines = [f"## ☀️ 持仓日报 — {now:%Y.%m.%d}", "",
             f"> {now:%M} ｜ 本金 {total_capital//10000}万 ｜ 盈利 +{total_pnl_total//10000 if total_pnl_total else '21'}万", ""]

    total_stock_value = 0
    total_pnl = 0

    if not hold:
        lines.append("### 💼 无持仓")
        lines.append(f"\n💰 现金 {cash:,.0f}元 ｜ 等待击球点")
    else:
        lines.append("### 💼 持仓明细")
        lines.append("")
        for code, v in hold.items():
            if not isinstance(v, dict):
                continue
            price = get_price(code)
            if price == 0:
                price = v.get("cost", 0)
            cost = v.get("cost", 0)
            shares = v.get("shares", 0)
            note = v.get("note", "")
            is_negative_cost = cost < 0

            if is_negative_cost:
                # 负成本持有：(现价 - 负成本) × 股数
                pnl = (price - cost) * shares
                stock_val = price * shares
                total_stock_value += stock_val
                total_pnl += pnl
                emoji = "🟢"
                lines.append(f"**{v.get('name', code)}** {emoji} [负成本]")
                lines.append(f"> {shares}股 成本负 现价{price:.2f} 市值{stock_val:,.0f} 盈亏 +{pnl:,.0f}元")
                lines.append(f"> 建仓 {v.get('date','')} | {note}")
            else:
                pnl_pct = (price - cost) / cost * 100 if cost else 0
                stock_val = price * shares
                total_stock_value += stock_val
                total_pnl += (price - cost) * shares
                emoji = "🟢" if pnl_pct > 5 else ("🟡" if pnl_pct > 0 else "🔴")
                lines.append(f"**{v.get('name', code)}** {emoji}")
                lines.append(f"> {shares}股 成本{cost} 现价{price:.2f} 市值{stock_val:,.0f} 盈亏{pnl_pct:+.1f}%")
                lines.append(f"> 建仓 {v.get('date','')} | 盈亏 {((price-cost)*shares):+.0f}元")

            # 卖出目标（股息率恢复）
            dps = trigger.get(code, {}).get("dps", 0)
            anchor = trigger.get(code, {}).get("anchor_pct", 0)
            if dps and anchor and not is_negative_cost:
                sell_target = round(dps / anchor * 100, 2)
                sell_gap = (sell_target - price) / price * 100 if price else 0
                lines.append(f"> 🎯 收租目标价 {sell_target:.2f}（距{sell_gap:+.1f}%）")

            if note:
                lines.append(f"> 📌 {note}")
            lines.append("")

        lines.append(f"💰 现金 {cash:,.0f}元")
        lines.append(f"📈 持仓市值 {total_stock_value:,.0f}元")
        lines.append(f"🏦 总资产 {total_stock_value+cash:,.0f}元")
        lines.append(f"📊 总盈亏 {total_pnl:+,.0f}元 | 仓位 {(total_stock_value/(total_stock_value+cash)*100):.1f}%")

    # 触发清单摘要
    hit = [(c, v) for c, v in trigger.items() if v.get("status") == "已触发"]
    close = [(c, v) for c, v in trigger.items() if v.get("status") == "接近"]
    if hit:
        lines.append(f"\n### 🔴 已触发 ({len(hit)}只)")
        for c, v in hit:
            lines.append(f"- {v['name']} 现价{v.get('current_price',0):.2f} 触发价{v['trigger_price']:.2f}")

    if close:
        lines.append(f"\n### 🟡 接近触发 ({len(close)}只)")
        for c, v in close:
            lines.append(f"- {v['name']} 现价{v.get('current_price',0):.2f} 触发价{v['trigger_price']:.2f}")

    events = state.get("events", [])
    if events:
        lines.append(f"\n### 📢 今日事件")
        for e in events:
            lines.append(f"- {e.get('name','')} {e.get('title','')} [{e.get('impact','')}]")

    lines.append(f"\n---\n{now:%Y-%m-%d %H:%M} | 持仓日报")

    push(f"☀️ 持仓日报 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
