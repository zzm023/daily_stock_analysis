"""
价格异动监控 v1
框架股 日涨跌幅 >5% 推送 | 配合触发价联动建议
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

THRESHOLD = 5.0  # 异动阈值%


def batch_tencent(codes):
    """腾讯批量 → {code: {name, price, change_pct, pe}}"""
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
                    name = parts[1] if parts[1] else c
                    change_pct = float(parts[32]) if parts[32] else None
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    if price:
                        results[c] = {
                            "name": name, "price": price,
                            "change_pct": change_pct, "pe": pe,
                        }
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
    print(f"[START] 价格异动 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    quotes = batch_tencent(codes)
    print(f"  行情 {len(quotes)} 只")

    up = []
    down = []

    for code in codes:
        q = quotes.get(code)
        if not q or q["change_pct"] is None:
            continue
        chg = q["change_pct"]
        if abs(chg) < THRESHOLD:
            continue

        t = trigger[code]
        tp = t.get("trigger_price", 0) if isinstance(t, dict) else 0
        is_held = code in hold
        near_tp = tp > 0 and abs(q["price"] - tp) / tp < 0.05

        row = {
            "name": q["name"],
            "price": q["price"],
            "change_pct": chg,
            "pe": q.get("pe"),
            "held": is_held,
            "near_tp": near_tp,
            "tp": tp,
        }

        if chg > 0:
            up.append(row)
        else:
            down.append(row)

    if not up and not down:
        print(f"  无 >{THRESHOLD}% 异动")
        return

    lines = [
        f"价格异动 {now:%m}.{now:%d}",
        f"涨跌幅 >{THRESHOLD:.0f}%",
    ]

    if up:
        lines.append("")
        lines.append(f"📈 大涨（{len(up)}只）")
        for r in sorted(up, key=lambda x: x["change_pct"], reverse=True):
            h = "★" if r["held"] else ""
            pe_s = f"PE{r['pe']:.0f}" if r["pe"] else ""
            tp_s = f" [接近触发价{r['tp']:.2f}]" if r["near_tp"] else ""
            lines.append(
                f"- {h}{r['name']} {r['price']:.2f} "
                f"{r['change_pct']:+.2f}%  {pe_s}{tp_s}"
            )

    if down:
        lines.append("")
        lines.append(f"📉 大跌（{len(down)}只）")
        for r in sorted(down, key=lambda x: x["change_pct"]):
            h = "★" if r["held"] else ""
            pe_s = f"PE{r['pe']:.0f}" if r["pe"] else ""
            tp_s = f" [接近触发价{r['tp']:.2f}]" if r["near_tp"] else ""
            lines.append(
                f"- {h}{r['name']} {r['price']:.2f} "
                f"{r['change_pct']:+.2f}%  {pe_s}{tp_s}"
            )

    lines.append("")
    lines.append("> ★持仓 | 接近=距触发价<5% | 大跌=关注加仓机会")

    push(f"异动 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 大涨{len(up)} 大跌{len(down)}")


if __name__ == "__main__":
    main()
