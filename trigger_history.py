"""
触发价历史追溯 v3
修复：52周高/低在 parts[36]/[37]
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_quote(codes):
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
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 40:
                    continue
                try:
                    now_price = float(parts[3]) if parts[3] else None
                    high_52 = float(parts[36]) if parts[36] else None      # 52周最高
                    low_52 = float(parts[37]) if parts[37] else None       # 52周最低
                    if low_52 and low_52 > 0:
                        result[c] = (now_price, low_52, high_52)
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
    print(f"[START] 触发价追溯 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    quotes = batch_quote(codes)

    hit = []
    never = []
    no_data = []

    for code in codes:
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        if not tp:
            continue

        q = quotes.get(code)
        if not q:
            no_data.append((name, tp))
            continue

        _, low_52, high_52 = q

        if low_52 <= tp:
            gap = round((tp - low_52) / low_52 * 100, 1)
            hit.append((name, tp, low_52, high_52, gap))
        else:
            gap = round((low_52 - tp) / tp * 100, 1)
            never.append((name, tp, low_52, high_52, gap))

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"52周高低 vs 触发价 | {len(quotes)}/{len(codes)}只有数据",
    ]

    if hit:
        lines.append("")
        lines.append(f"触发过 {len(hit)}只 — 合理")
        for name, tp, low, high, gap in sorted(hit, key=lambda x: -x[3]):
            lines.append(f"  - {name} 触发{tp:.2f} 低{low:.2f} 穿透{gap:.0f}%")

    if never:
        lines.append("")
        lines.append(f"从未触发 {len(never)}只 — 可能偏高")
        never.sort(key=lambda x: x[4])  # gap 小的排前
        for name, tp, low, high, gap in never[:15]:
            lines.append(f"  - {name} 触发{tp:.2f} 低{low:.2f} 高{high:.2f} 距低{gap}%")
        if len(never) > 15:
            lines.append(f"  ...等{len(never)}只")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")

    lines.append("")
    lines.append(f"> 触发≤52周低=合理")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发过{len(hit)} 从未{len(never)}")


if __name__ == "__main__":
    main()
