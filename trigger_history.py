"""
触发价历史追溯 v7
东财快照逐只取 + sleep 防限流 → 稳定的 52 周高低
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_52w(code):
    prefix = "1" if code.startswith("6") else "0"
    secid = f"{prefix}.{code}"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": secid,
                "fields": "f43,f51,f52",
            },
            timeout=10,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data")
        if not data:
            return None
        p = data.get("f43")
        h = data.get("f51")
        l = data.get("f52")
        if not l:
            return None
        return {
            "price": p / 100 if p else None,
            "high_52": h / 100 if h else None,
            "low_52": l / 100 if l else None,
        }
    except:
        return None


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
    print(f"[START] 触发价追溯 v7 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]

    hit, never, no_data = [], [], []

    for i, code in enumerate(codes):
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        if not tp:
            continue

        d = get_52w(code)
        if i % 5 == 4:
            time.sleep(0.3)

        if not d or not d["low_52"]:
            no_data.append((name, tp))
            continue

        low = d["low_52"]
        high = d["high_52"]

        if low <= tp:
            gap = round((tp - low) / low * 100, 1)
            hit.append((name, tp, low, high, gap))
        else:
            gap = round((low - tp) / tp * 100, 1)
            never.append((name, tp, low, high, gap))

        print(f"  [{i+1}/{len(codes)}] {name} 触{tp} 52低{low}")

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"52周高低 vs 触发价 | {len(hit)+len(never)}/{len(codes)}只有数据",
    ]

    if hit:
        hit.sort(key=lambda x: -x[4])
        lines.append("")
        lines.append(f"触发过 {len(hit)}只 — 合理")
        for name, tp, low, high, gap in hit[:10]:
            lines.append(f"  - {name} 触发{tp:.2f} 52低{low:.2f} 52高{high:.2f} 穿透{gap}%")

    if never:
        never.sort(key=lambda x: x[4])
        lines.append("")
        lines.append(f"从未触发 {len(never)}只 — 可能偏高")
        for name, tp, low, high, gap in never[:15]:
            lines.append(f"  - {name} 触发{tp:.2f} 52低{low:.2f} 52高{high:.2f} 距{gap}%")
        if len(never) > 15:
            lines.append(f"  ...等{len(never)}只")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")

    lines.append("")
    lines.append(f"> 触发≤52低=合理 | 触发>52低=偏严")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发过{len(hit)} 从未{len(never)}")


if __name__ == "__main__":
    main()
