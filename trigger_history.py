"""
触发价历史追溯 v2
腾讯API → 52周最低价 vs 触发价 → 判断是否合理
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_quote(codes):
    """取 52周最低 + 当前价"""
    result = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if m:
                    parts = m.group().split("~")
                    if len(parts) >= 50:
                        try:
                            now_price = float(parts[3]) if parts[3] else 0
                            low_52 = float(parts[40]) if parts[40] else 0  # 52周最低
                            result[c] = (now_price, low_52)
                        except:
                            pass
        except Exception as e:
            print(f"  取价失败: {e}")
    return result


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
    print(f"[START] 触发价追溯 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    quotes = batch_quote(codes)

    hit = []       # 触发过（价曾低于触发）
    never = []     # 从未触发
    no_data = []   # 无数据

    for code in codes:
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        if not tp:
            continue

        q = quotes.get(code)
        if not q or not q[1]:
            no_data.append((name, tp))
            continue

        price_52low = q[1]

        if price_52low <= tp:
            gap = round((tp - price_52low) / price_52low * 100, 1)
            hit.append((name, tp, price_52low, gap))
        else:
            gap = round((tp - price_52low) / price_52low * 100, 1)
            never.append((name, tp, price_52low, gap))

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"52周最低 vs 触发价 | 共{len(codes)}只",
    ]

    if hit:
        lines.append("")
        lines.append(f"触发过 {len(hit)}只 — 价合理")
        for name, tp, low, gap in sorted(hit, key=lambda x: -x[3]):
            lines.append(f"  - {name} 触发{tp:.2f} 52周低{low:.2f} 穿透{gap:.0f}%")

    if never:
        lines.append("")
        lines.append(f"从未触发 {len(never)}只 — 可能偏高↓")
        for name, tp, low, gap in sorted(never, key=lambda x: x[3])[:15]:
            lines.append(f"  - {name} 触发{tp:.2f} 52周低{low:.2f} 差{gap:.0f}%")
        if len(never) > 15:
            lines.append(f"  ...等{len(never)}只")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")
        for name, tp in no_data[:5]:
            lines.append(f"  - {name} {tp:.2f}")

    lines.append("")
    lines.append(f"> 触发≤52周低=合理 | 触发>52周低=偏严")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发过{len(hit)} 从未{len(never)}")


if __name__ == "__main__":
    main()
