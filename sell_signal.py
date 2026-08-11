"""
卖出信号 v1
清除目录监控 + 持仓跌破触发价提醒
"""
import os
import json
import requests
import re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 跌破触发价阈值（距触发价下方多少%才提醒）
BREAK_THRESHOLD = -5.0


def batch_tencent(codes):
    results = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i + 30]
        symbols = ",".join(
            f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch
        )
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 48:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    change_pct = float(parts[32]) if parts[32] else None
                    if price:
                        results[c] = {"price": price, "change_pct": change_pct}
                except Exception:
                    pass
        except Exception:
            pass
    return results


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
    print(f"[START] 卖出信号 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    clear_list = state.get("clear_list", {})  # 清除目录
    cash = hold.get("cash", 0)

    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]

    # 行情
    all_codes = set(hold_codes)
    if clear_list:
        all_codes |= set(c for c in clear_list)
    quotes = batch_tencent(list(all_codes))

    alerts = []

    # 1. 持仓跌破触发价
    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        q = quotes.get(code, {})
        price = q.get("price", 0)
        if not price:
            continue

        tp = 0
        if isinstance(trigger.get(code), dict):
            tp = trigger[code].get("trigger_price", 0)
        if tp <= 0:
            continue

        dist_pct = (price - tp) / tp * 100
        if dist_pct <= BREAK_THRESHOLD:
            cost = v.get("cost", 0)
            cost_chg = (price - cost) / cost * 100 if cost > 0 else 0
            alerts.append({
                "type": "跌破触发价",
                "name": name,
                "price": price,
                "tp": tp,
                "dist_pct": dist_pct,
                "cost_chg": cost_chg,
                "shares": v.get("shares", 0),
            })

    # 2. 清除目录异常大涨（可能反弹诱多）
    if clear_list:
        for code in clear_list:
            cl = clear_list[code]
            name = cl.get("name", code) if isinstance(cl, dict) else code
            q = quotes.get(code, {})
            price = q.get("price", 0)
            chg = q.get("change_pct")
            if not price:
                continue
            reason = cl.get("reason", "未说明") if isinstance(cl, dict) else "未说明"
            if chg and chg > 5:
                alerts.append({
                    "type": "清除股大涨",
                    "name": name,
                    "price": price,
                    "change_pct": chg,
                    "reason": reason,
                })

    if not alerts:
        print("  无卖出信号")
        return

    lines = [
        f"卖出信号 {now:%m}.{now:%d}",
        f"跌破{BREAK_THRESHOLD:+.0f}%提醒 | 清除股异动监控",
    ]

    for a in alerts:
        lines.append("")
        if a["type"] == "跌破触发价":
            lines.append(
                f"⚠️ {a['name']} 跌破触发价"
            )
            lines.append(
                f"   现{a['price']:.2f} | 触发{a['tp']:.2f} "
                f"跌破{a['dist_pct']:+.1f}% "
                f"成本盈亏{a['cost_chg']:+.1f}%"
            )
        elif a["type"] == "清除股大涨":
            lines.append(
                f"👀 {a['name']} 清除股大涨 "
                f"{a['change_pct']:+.1f}% | {a['reason']}"
            )

    lines.append("")
    lines.append("> 跌破触发价不代表清仓 | 需审视基本面是否变化")

    push(f"卖出信号 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] {len(alerts)}条信号")


if __name__ == "__main__":
    main()
