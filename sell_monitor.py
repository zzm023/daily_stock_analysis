"""
卖出信号监控 v1
每日检查持仓 → 现价≥收租目标价 → 推送收割提醒
每日 15:00 CST（触发价监控之后）
"""
import os
import json
import requests
import subprocess
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


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
    print(f"[START] 卖出信号监控 v1 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    sell_signals = []
    no_anchor = []
    approaching = []

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue

        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        note = v.get("note", "")

        # 负成本跳过
        if cost < 0:
            print(f"  {name}: 负成本持有，跳过")
            continue

        price = get_price(code)
        if price == 0:
            print(f"  {name}: 获取价格失败")
            continue

        pnl_pct = (price - cost) / cost * 100

        # 查收租目标价
        t = trigger.get(code, {})
        dps = t.get("dps", 0)
        anchor = t.get("anchor_pct", 0)

        if dps and anchor:
            target = round(dps / anchor * 100, 2)
            yld = dps / cost * 100
            gap_to_target = (target - price) / price * 100

            if price >= target:
                sell_signals.append((name, code, price, target, cost, shares, pnl_pct, yld))
                print(f"  🔔 {name}: 现{price:.2f} ≥ 目标{target:.2f} → 收割信号！")
            elif gap_to_target <= 10:
                approaching.append((name, code, price, target, gap_to_target, pnl_pct))
                print(f"  ⏳ {name}: 现{price:.2f} 目标{target:.2f} 距{abs(gap_to_target):.1f}%")
            else:
                print(f"  {name}: 现{price:.2f} 目标{target:.2f} 距{abs(gap_to_target):.1f}%")
        else:
            no_anchor.append(name)
            print(f"  {name}: 现{price:.2f} 盈亏{pnl_pct:+.1f}% — 无收租锚定")

    if no_anchor:
        print(f"  无锚定: {len(no_anchor)}只 ({', '.join(no_anchor)})")

    if not sell_signals and not approaching:
        print("[DONE] 无卖出信号")
        return

    # 组装推送
    lines = [f"## 💰 卖出信号 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 持仓{len(hold)-1}只", ""]

    if sell_signals:
        lines.append("### 🔔 已达收租目标（可收割）")
        lines.append("")
        lines.append("| 股票 | 现价 | 目标 | 成本 | 盈亏 | 成本息率 |")
        lines.append("|------|------|------|------|------|------|")
        for name, code, price, target, cost, shares, pnl, yld in sell_signals:
            lines.append(f"| {name} | {price:.2f} | {target:.2f} | {cost:.2f} | {pnl:+.1f}% | {yld:.1f}% |")
        lines.append("")
        lines.append("> 💡 收租目标价 = 目标股息率恢复点。达到后可收割，或继续持有吃息。")
        lines.append("")

    if approaching:
        lines.append("### ⏳ 接近收租目标（≤10%）")
        lines.append("")
        lines.append("| 股票 | 现价 | 目标 | 差距 | 盈亏 |")
        lines.append("|------|------|------|------|------|")
        for name, code, price, target, gap, pnl in approaching:
            lines.append(f"| {name} | {price:.2f} | {target:.2f} | {abs(gap):.1f}% | {pnl:+.1f}% |")
        lines.append("")

    push(f"💰 卖出信号 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
