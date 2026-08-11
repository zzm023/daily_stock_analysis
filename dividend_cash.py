"""
分红金额预测 v9
手工维护每股分红 + 持股数 → 精确到元
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# ============================================
# 手工维护：每股分红（元/股），每季度更新
# 格式: 代码: (每股分红, 除权日, 到账日, 来源年报)
# 2025年报分红(2026年实施) 查自东财公告
# ============================================
DIVIDEND_MANUAL = {
    # 已公告2025年报分红的
    "002027": (0.19, "2026-06-15", "2026-06-16", "2025年报"),
    "600690": (0.89, "2026-07-10", "2026-07-11", "2025年报"),
    "000708": (0.45, "2026-06-20", "2026-06-23", "2025年报"),
    "600845": (0.23, "2026-06-05", "2026-06-06", "2025年报"),
    "000157": (0.20, "2026-07-25", "2026-07-28", "2025年报"),
    "002601": (0.6, "2026-05-15", "2026-05-16", "2025年报"),
    "600161": (0.05, ),
    "300498": (0.20, ),
    # 未公告或不分红的
    "002747": (0.00, "", "", "无分红"),
}


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        requests.post(
            "http://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown",
                "topic": PUSHPLUS_TOPIC,
            },
            timeout=10
        )
    except Exception:
        pass


def main():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    print(f"[START] 分红金额 v9 {today_str}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    received, pending, upcoming, no_div, no_data = [], [], [], [], []
    total_received = total_pending = total_upcoming = 0

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)

        d = DIVIDEND_MANUAL.get(code)
        if d is None:
            no_data.append(name)
            continue

        dps, ex_date, pay_date, source = d
        total = shares * dps

        if dps == 0:
            no_div.append(name)
            continue

        print(f"  {name} {dps}/股 × {shares}股 = {total:.0f}元")

        if pay_date and pay_date <= today_str:
            received.append((name, dps, total, pay_date, source))
            total_received += total
        elif ex_date and ex_date <= today_str:
            pending.append((name, dps, total, pay_date, source))
            total_pending += total
        else:
            upcoming.append((name, dps, total, ex_date, pay_date, source))
            total_upcoming += total

    total_all = total_received + total_pending + total_upcoming

    lines = [
        f"分红金额 {now:%m}.{now:%d}",
        f"持仓{len(hold_codes)}只 | 全年{total_all/10000:.2f}万",
    ]

    if received:
        lines.append("")
        lines.append(f"✅ 已到账 {total_received/10000:.2f}万")
        for n, dps, t, d, src in received:
            lines.append(f"  - {n} {dps}/股 × 持仓 = {t:.0f}元 ({d}) [{src}]")

    if pending:
        lines.append("")
        lines.append(f"⏳ 已除权待收款 {total_pending/10000:.2f}万")
        for n, dps, t, d, src in pending:
            lines.append(f"  - {n} {t:.0f}元 → {d} [{src}]")

    if upcoming:
        lines.append("")
        lines.append(f"📅 待除权 {total_upcoming/10000:.2f}万")
        for n, dps, t, ex, pay, src in upcoming:
            lines.append(f"  - {n} {dps}/股 = {t:.0f}元 → 除权{ex} [{src}]")

    if no_div:
        lines.append("")
        lines.append(f"无分红 {len(no_div)}只")
        lines.append(f"  {', '.join(no_div[:6])}")

    if no_data:
        lines.append("")
        lines.append(f"⚠️ 待补充 {len(no_data)}只")
        lines.append(f"  {', '.join(no_data)}")

    if not received and not pending and not upcoming and not no_div:
        lines.append("")
        lines.append("8月A股分红真空期（年报分红5-7月已结束，半年报10月开始）")

    lines.append("")
    lines.append("> 手工维护每股分红 | 准确性取决于数据时效")

    push(f"分红金额 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 总计{total_all:.0f}元")


if __name__ == "__main__":
    main()
