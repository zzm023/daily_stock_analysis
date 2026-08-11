"""
距触发价排行 v4
去截断 → 全量显示
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
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    if price:
                        results[c] = {"price": price, "pe": pe}
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
    print(f"[START] 距触发价排行 v4 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    quotes = batch_tencent(codes)

    rows = []
    for code in codes:
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        if tp <= 0:
            continue
        q = quotes.get(code, {})
        price = q.get("price", 0)
        if price <= 0:
            continue
        rows.append({
            "name": name,
            "price": price,
            "pe": q.get("pe"),
            "dist_pct": (price - tp) / tp * 100,
            "held": code in hold,
        })

    rows.sort(key=lambda x: x["dist_pct"])

    triggered = [r for r in rows if r["dist_pct"] <= 0]
    close = [r for r in rows if 0 < r["dist_pct"] <= 10]
    mid = [r for r in rows if 10 < r["dist_pct"] <= 30]
    far = [r for r in rows if r["dist_pct"] > 30]

    def item(r):
        h = "★" if r["held"] else "-"
        p = f"PE{r['pe']:.0f}" if r["pe"] else ""
        return f"{h} {r['name']} {r['price']:.2f}  {r['dist_pct']:+.1f}%  {p}"

    total = len(rows)
    lines = [
        f"触发价排行 {now:%m}.{now:%d} 共{total}只",
        f"★持仓 | 负值=已触发",
    ]

    for label, group, emoji in [
        ("已触发", triggered, "🎯"),
        ("接近 <10%", close, ""),
        ("较远 10-30%", mid, ""),
        ("遥远 >30%", far, ""),
    ]:
        if not group:
            continue
        lines.append("")
        lines.append(f"{emoji} {label}（{len(group)}只）")
        for r in group:
            lines.append(item(r))

    push(f"触发价排行 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
