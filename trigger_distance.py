"""
距触发价排行 v1
全框架股 现价/触发价 → 排序 → 谁最接近击球区
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
    print(f"[START] 距触发价排行 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    print(f"  框架股 {len(codes)} 只")

    quotes = batch_tencent(codes)
    print(f"  行情 {len(quotes)} 只")

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

        pe = q.get("pe")
        dist_pct = (price - tp) / tp * 100
        is_held = code in hold

        rows.append({
            "name": name,
            "code": code,
            "price": price,
            "tp": tp,
            "pe": pe,
            "dist_pct": dist_pct,
            "held": is_held,
        })

    rows.sort(key=lambda x: x["dist_pct"])

    # 分组
    triggered = [r for r in rows if r["dist_pct"] <= 0]
    close = [r for r in rows if 0 < r["dist_pct"] <= 10]
    mid = [r for r in rows if 10 < r["dist_pct"] <= 30]
    far = [r for r in rows if r["dist_pct"] > 30]

    def fmt(r):
        held = "★" if r["held"] else " "
        pe_s = f"PE{r['pe']:.0f}" if r["pe"] else ""
        return (f"{held}{r['name']} "
                f"{r['price']:.2f} "
                f"距{r['dist_pct']:+.1f}% "
                f"{pe_s}")

    lines = [
        f"距触发价排行 {now:%m}.{now:%d}",
        f"现价/触发价 | ★=已持仓",
    ]

    if triggered:
        lines.append("")
        lines.append(f"🎯 已触发 {len(triggered)}只")
        for r in triggered:
            lines.append(fmt(r))

    if close:
        lines.append("")
        lines.append(f"🟢 接近(<10%) {len(close)}只")
        for r in close:
            lines.append(fmt(r))

    if mid:
        lines.append("")
        lines.append(f"🟡 较远(10-30%) {len(mid)}只")
        for r in mid[:5]:
            lines.append(fmt(r))
        if len(mid) > 5:
            lines.append(f"  ...等{len(mid)-5}只")

    if far:
        lines.append("")
        lines.append(f"🔴 遥远(>30%) {len(far)}只")
        for r in far[:5]:
            lines.append(fmt(r))
        if len(far) > 5:
            lines.append(f"  ...等{len(far)-5}只")

    lines.append("")
    lines.append("> 距=现价高于触发价% | 负值=已触发")

    push(f"距触发价排行 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发{len(triggered)} 接近{len(close)} 较远{len(mid)} 遥远{len(far)}")


if __name__ == "__main__":
    main()
