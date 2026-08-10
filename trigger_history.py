"""
触发价历史追溯 v10（最终版）
腾讯 parts[41]/[42] = 近期波动区间 / 50只全覆盖
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_range(codes):
    """腾讯批量 parts[41]=近期高 parts[42]=近期低"""
    result = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i+30]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            text = r.text
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 45:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    high = float(parts[41]) if parts[41] else None
                    low = float(parts[42]) if parts[42] else None
                    if (price and high and low and high > 0 and low > 0
                        and 0.3*price < low < 3*price
                        and 0.3*price < high < 3*price):
                        result[c] = (price, high, low)
                except:
                    pass
        except Exception as e:
            print(f"  批次失败: {e}")
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
    print(f"[START] 触发价追溯 v10 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    data = batch_range(codes)
    print(f"  获取 {len(data)}/{len(codes)} 只")

    hit = []
    never = []

    for code in codes:
        t = trigger[code]
        tp = t.get("trigger_price", 0)
        name = t.get("name", code)
        if not tp:
            continue
        d = data.get(code)
        if not d:
            continue
        _, high, low = d

        if low <= tp:
            gap = round((tp - low) / low * 100, 1)
            hit.append((name, tp, low, high, gap))
        else:
            gap = round((low - tp) / tp * 100, 1)
            never.append((name, tp, low, high, gap))

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"近期波动 vs 触发价 | {len(data)}/{len(codes)}只",
        "",
    ]

    # 全文总结
    touchable = [n for n,_,l,_,_ in hit if tp] + [n for n,_,l,_,g in never if g <= 5]
    strict = len(never) - len([n for n,_,_,_,g in never if g <= 5])

    lines.append(f"触发过的 {len(hit)}只 | 距触发≤5% {len([1 for _,_,_,_,g in never if g <= 5])}只 | 偏严 {strict}只")
    lines.append("")

    if hit:
        lines.append("触发过（价合理）")
        for name, tp, low, high, gap in sorted(hit, key=lambda x: -x[4])[:8]:
            lines.append(f"  - {name} 触发{tp:.2f} 近期低{low:.2f} 穿透{gap}%")

    close = [(n, tp, l, h, g) for n, tp, l, h, g in never if g <= 5]
    if close:
        lines.append("")
        lines.append("距触发≤5%（接近）")
        for name, tp, low, high, gap in sorted(close, key=lambda x: x[4])[:10]:
            lines.append(f"  - {name} 触发{tp:.2f} 近期低{low:.2f} 距{gap}%")

    far = [(n, tp, l, h, g) for n, tp, l, h, g in never if g > 5]
    if far:
        lines.append("")
        lines.append(f"距触发>5%（{len(far)}只）")
        for name, tp, low, high, gap in sorted(far, key=lambda x: x[4])[:8]:
            lines.append(f"  - {name} 触发{tp:.2f} 近期低{low:.2f} 距{gap}%")

    lines.append("")
    lines.append(f"> 腾讯数据 parts[41/42]=近期波动区间 | 非52周")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发过{len(hit)} 接近{len(close)} 偏严{len(far)}")


if __name__ == "__main__":
    main()
