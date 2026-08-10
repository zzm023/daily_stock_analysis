"""
触发价历史追溯 v6
东财批量API → 一次取50只52周高低
"""
import os, json, requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_52w(codes):
    """东财批量 → {code: {price, high_52, low_52}}"""
    secids = ",".join(f"1.{c}" if c.startswith("6") else f"0.{c}" for c in codes)
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params={
                "secids": secids,
                "fields": "f2,f12,f51,f52",
                "fltt": "2",
            },
            timeout=15,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data")
        if not data:
            return {}
        result = {}
        for item in data.get("diff", []):
            code = item.get("f12", "")
            if not code:
                continue
            result[code] = {
                "price": item.get("f2", 0) if item.get("f2") else None,
                "high_52": item.get("f51", 0) if item.get("f51") else None,
                "low_52": item.get("f52", 0) if item.get("f52") else None,
            }
        return result
    except Exception as e:
        print(f"  批量取价失败: {e}")
        return {}


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
    print(f"[START] 触发价追溯 v6 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    data = batch_52w(codes)
    print(f"  获取到 {len(data)}/{len(codes)} 只")

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

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"52周高低 vs 触发价 | {len(data)}/{len(codes)}只有数据",
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
