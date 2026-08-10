"""
触发价历史追溯 v4
东财日K线 → 遍历过去2年实际高低 → 靠谱
"""
import os, json, requests, re
from datetime import datetime, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def fetch_daily(code):
    """东财日K前复权 → [(日期,开盘,最高,最低,收盘)]"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    end = datetime.now().strftime("%Y%m%d")
    beg = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")
    try:
        r = requests.get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": secid, "klt": "101", "fqt": "1",
                "beg": beg, "end": end,
                "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55",
            },
            timeout=15,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data", {})
        klines = data.get("klines", [])
        if not klines:
            return None, None, None

        # 遍历找最低/最高
        low_all = float("inf")
        high_all = 0
        hit_dates = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 5:
                continue
            date = parts[0][:10]
            o = float(parts[1]) if parts[1] != "-" else 0
            c = float(parts[2]) if parts[2] != "-" else 0
            h = float(parts[3]) if parts[3] != "-" else 0
            l = float(parts[4]) if parts[4] != "-" else 0
            if l > 0:
                low_all = min(low_all, l)
            if h > 0:
                high_all = max(high_all, h)
            if l > 0 and c > 0:
                # 最低价 ≤ 触发价 算命中（用收盘价模拟触发检查）
                pass  # 后面用 low_all 判断

        return low_all if low_all != float("inf") else None, high_all if high_all > 0 else None, klines

    except Exception as e:
        return None, None, None


def check_hits(klines, tp):
    """统计触发次数：日最低价 ≤ 触发价"""
    hits = 0
    for line in klines:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        l = float(parts[4]) if parts[4] != "-" else 0
        if l > 0 and l <= tp:
            hits += 1
    return hits


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
    print(f"[START] 触发价追溯 v4 {now:%Y-%m-%d}")

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

        low_all, high_all, klines = fetch_daily(code)
        print(f"  [{i+1}/{len(codes)}] {name} low={low_all} tp={tp}")

        if low_all is None:
            no_data.append((name, tp))
            continue

        n_hits = check_hits(klines, tp) if klines else 0

        if low_all <= tp:
            gap = round((tp - low_all) / low_all * 100, 1)
            hit.append((name, tp, low_all, high_all, n_hits, gap))
        else:
            gap = round((low_all - tp) / tp * 100, 1)
            never.append((name, tp, low_all, high_all, gap))

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"日K最低价 vs 触发价 | 过去2年 | {len(codes)-len(no_data)}只有数据",
    ]

    if hit:
        hit.sort(key=lambda x: -x[4])  # 命中天数多排前
        lines.append("")
        lines.append(f"触发过 {len(hit)}只 — 价合理")
        for name, tp, low, high, n, gap in hit[:10]:
            lines.append(f"  - {name} 触发{tp:.2f} 低{low:.2f} 高{high:.2f} 命中{n}天 穿透{gap:.0f}%")
        if len(hit) > 10:
            lines.append(f"  ...等{len(hit)}只")

    if never:
        never.sort(key=lambda x: x[4])
        lines.append("")
        lines.append(f"从未触发 {len(never)}只 — 可能偏高↓")
        for name, tp, low, high, gap in never[:12]:
            lines.append(f"  - {name} 触发{tp:.2f} 最低{low:.2f} 距{gap}%")
        if len(never) > 12:
            lines.append(f"  ...等{len(never)}只")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")

    lines.append("")
    lines.append(f"> 触发价≤历史最低=合理 | 从未跌破=偏严")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 触发过{len(hit)} 从未{len(never)}")


if __name__ == "__main__":
    main()
