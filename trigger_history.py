"""
触发价历史追溯 v9
尝试 parts[43]=52周高 parts[44]=52周低 + 合理性校验
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_52w(codes):
    """腾讯批量 → {code: (price, high_52, low_52)} 尝试 indices 43/44"""
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
                if len(parts) < 47:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    # 尝试 indices 43/44（可能为52周高低）
                    high_52 = float(parts[43]) if parts[43] else None
                    low_52 = float(parts[44]) if parts[44] else None
                    # 校验：合理范围 = 现价 0.3x ~ 3x
                    if (high_52 and price and 0.3*price < high_52 < 3*price and
                        low_52 and 0.3*price < low_52 < 3*price):
                        result[c] = (price, high_52, low_52)
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
    print(f"[START] 触发价追溯 v9 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    data = batch_52w(codes)
    print(f"  获取 {len(data)}/{len(codes)} 只")

    hit = []
    never = []
    no_data = []

    for code in codes:
        t = trigger[code]
        tp = t.get("trigger_price", 0)
        name = t.get("name", code)
        if not tp:
            continue

        d = data.get(code)
        if not d:
            no_data.append((name, tp))
            continue

        _, high, low = d

        if low <= tp:
            gap_pct = round((tp - low) / low * 100, 1)
            hit.append((name, tp, low, high, gap_pct))
        else:
            gap_pct = round((low - tp) / tp * 100, 1)
            never.append((name, tp, low, high, gap_pct))

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"历史区间 vs 触发价 | {len(data)}/{len(codes)}只有数据",
    ]

    if hit:
        hit.sort(key=lambda x: -x[4])
        lines.append("")
        lines.append(f"触发过 {len(hit)}只 — 价合理")
        for name, tp, low, high, gap in hit[:12]:
            lines.append(f"  - {name} 触发{tp:.2f} 低{low:.2f} 高{high:.2f} 穿透{gap}%")

    if never:
        never.sort(key=lambda x: x[4])
        lines.append("")
        lines.append(f"从未触发 {len(never)}只")
        for name, tp, low, high, gap in never[:15]:
            lines.append(f"  - {name} 触发{tp:.2f} 低{low:.2f} 高{high:.2f} 距{gap}%")
        if len(never) > 15:
            lines.append(f"  ...等{len(never)}只")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")

    lines.append("")
    lines.append(f"> 触发≤最低=合理 | 触发>最低=偏严")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发过{len(hit)} 从未{len(never)}")


if __name__ == "__main__":
    main()
