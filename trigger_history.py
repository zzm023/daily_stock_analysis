"""
触发价历史追溯 v1
东财周K线数据 → 过去2年触发次数/最低点/平均反弹
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def fetch_weekly(code):
    """东财周K线 → [(日期,收盘价)]"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    try:
        r = requests.get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": secid, "klt": "105", "fqt": "1",  # 复权
                "beg": "20240101", "end": datetime.now().strftime("%Y%m%d"),
                "fields1": "f1,f2", "fields2": "f51",
            },
            timeout=15, headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data", {})
        klines = data.get("klines", [])
        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 3:
                rows.append((parts[0][:10], float(parts[2])))
        return rows
    except:
        return []


def analyze(rows, trigger_price):
    """遍历周线：每当收盘价低于触发价 → 记录信号
    返回触发次数 / 最低点 / 平均反弹%"""
    below = False
    low = None
    entry = None
    rebounds = []
    trigger_count = 0

    for date, close in rows:
        if not below and close <= trigger_price:
            below = True
            entry = close
            low = close
            trigger_count += 1
        elif below:
            low = min(low, close) if low else close
            if close > trigger_price * 1.05:  # 反弹 5% 算结束
                if entry and entry > 0:
                    rebounds.append(round((close - entry) / entry * 100, 1))
                below = False
                entry = None
                low = None

    if trigger_count == 0:
        return 0, None, None

    avg_rebound = round(sum(rebounds) / len(rebounds), 1) if rebounds else None
    return trigger_count, low, avg_rebound


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
    print(f"[START] 触发价追溯 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]

    results = []
    for i, code in enumerate(codes):
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        if not tp:
            continue

        print(f"  [{i+1}/{len(codes)}] {name}...")
        rows = fetch_weekly(code)
        n, low, avg_r = analyze(rows, tp)

        results.append({
            "name": name, "tp": tp,
            "hits": n, "low": low, "avg_rebound": avg_r,
        })

    results.sort(key=lambda x: x["hits"], reverse=True)

    lines = [
        f"触发价追溯 {now:%m}.{now:%d}",
        f"过去2年周线 | 共{len(results)}只",
    ]

    hit_count = sum(1 for r in results if r["hits"] > 0)
    lines.append("")
    lines.append(f"有触发记录：{hit_count}只")

    for r in results:
        if r["hits"] == 0:
            continue
        parts = [f"- **{r['name']}** 触发{r['tp']:.2f} 命中{r['hits']}次"]
        if r["low"]:
            parts.append(f"最低{r['low']:.2f}")
        if r["avg_rebound"] is not None:
            parts.append(f"均反弹{r['avg_rebound']:+.1f}%")
        lines.append(" ".join(parts))

    # 从未触发的
    never = [r for r in results if r["hits"] == 0]
    if never:
        lines.append("")
        lines.append(f"从未触发：{len(never)}只")
        lines.append("触发价可能偏激进↓")
        for r in never[:10]:
            lines.append(f"  {r['name']} {r['tp']:.2f}")

    lines.append("")
    lines.append(f"> 命中多次=触发价合理 | 0次=可能偏高")

    push(f"触发价追溯 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
