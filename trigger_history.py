"""
触发价历史追溯 v5
东财快照API → f51/f52 = 52周高/低 → 分转元
"""
import os, json, requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_52w(code):
    """东财快照 → {price, high_52, low_52} 单位元"""
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
        # 东财返回单位"分"
        return {
            "price": data.get("f43", 0) / 100 if data.get("f43") else None,
            "high_52": data.get("f51", 0) / 100 if data.get("f51") else None,
            "low_52": data.get("f52", 0) / 100 if data.get("f52") else None,
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
    print(f"[START] 触发价追溯 v5 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]

    hit = []
    never = []
    no_data = []

    for i, code in enumerate(codes):
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        if not tp:
            continue

        d = get_52w(code)
        print(f"  [{i+1}/{len(codes)}] {name} tp={tp} data={d}")
        if not d or not d["low_52"]:
            no_data.append((name, tp))
            continue

        low = d["low_52"]
        high = d["high_52"]

        if low <= tp:
            gap = (tp - low) / low * 100
            hit.append((name, tp, low, high, gap))
        else:
            gap = (low - tp) / tp * 100
            never.append((name, tp, low, high, gap))

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"52周高低 vs 触发价 | {len(codes)-len(no_data)}/{len(codes)}只有数据",
    ]

    if hit:
        hit.sort(key=lambda x: -x[4])
        lines.append("")
        lines.append(f"触发过 {len(hit)}只 — 合理")
        for name, tp, low, high, gap in hit[:10]:
            lines.append(f"  - {name} 触发{tp:.2f} 52低{low:.2f} 52高{high:.2f} 穿透{gap:.0f}%")

    if never:
        never.sort(key=lambda x: x[4])
        lines.append("")
        lines.append(f"从未触发 {len(never)}只")
        for name, tp, low, high, gap in never[:12]:
            lines.append(f"  - {name} 触发{tp:.2f} 52低{low:.2f} 距{gap:.0f}%")
        if len(never) > 12:
            lines.append(f"  ...等{len(never)}只")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")

    lines.append("")
    lines.append(f"> 触发≤52低=合理")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发过{len(hit)} 从未{len(never)}")


if __name__ == "__main__":
    main()
