"""
复盘笔记 v2
修复：列表格式 / 日变首跑提示
"""
import os, json, requests, re
from datetime import datetime, timedelta
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
            text = r.text
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", text)
                if m:
                    parts = m.group().split("~")
                    if len(parts) >= 4 and parts[3]:
                        prices[c] = float(parts[3])
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
    print(f"[START] 复盘笔记 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    cash = hold.get("cash", 0)
    trigger = state.get("trigger", {})
    sell_signals = state.get("sell_signals", [])
    prev = state.get("snapshot", {})

    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    fw_codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    all_codes = list(set(hold_codes + fw_codes))
    prices = batch_prices(all_codes)

    total_cost = 0
    total_mv = 0
    for code in hold_codes:
        v = hold[code]
        if not isinstance(v, dict):
            continue
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        price = prices.get(code, 0)
        if cost < 0:
            total_mv += price * shares if price else 0
        else:
            total_cost += cost * shares
            total_mv += price * shares if price else cost * shares

    total_pnl = total_mv - total_cost
    prev_pnl = prev.get("total_pnl", total_pnl)
    pnl_change = total_pnl - prev_pnl
    change_str = f"{pnl_change/10000:+.1f}万" if prev else "首跑"

    lines = [
        f"复盘 {now:%m}.{now:%d}",
        f"总{(total_mv+cash)/10000:.0f}万 盈亏{total_pnl/10000:+.1f}万 日变{change_str}",
    ]

    # 新接近触发
    approaching = []
    for code, t in trigger.items():
        if not isinstance(t, dict) or code in hold_codes:
            continue
        name = t.get("name", code)
        target = t.get("trigger_price", 0)
        price = prices.get(code, 0)
        if not price or not target:
            continue
        gap = (price - target) / target * 100
        if gap <= 10:
            res = "⚡" if "双振" in t.get("resonance", "") else ""
            approaching.append((gap, f"- {name} {price:.2f}→{target:.2f} {gap:+.1f}% {res}"))

    lines.append("")
    lines.append(f"触发≤10%：{len(approaching)}只")
    for _, s in sorted(approaching):
        lines.append(s)

    # 卖出
    lines.append("")
    lines.append(f"卖出：{'有信号' if sell_signals else '无'}")

    lines.append("")
    lines.append(f"{now:%H:%M}")

    state["snapshot"] = {
        "date": now.strftime("%Y-%m-%d"),
        "total_mv": total_mv,
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "cash": cash,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    push(f"复盘 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
