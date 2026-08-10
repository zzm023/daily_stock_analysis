"""
主力资金哨兵 v1
东财单只取 f62=当日主力净流入 f184=5日净流入 f64=占比
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_flow(code):
    """东财单只 → {price, flow_day, flow_5d, flow_pct}"""
    prefix = "1" if code.startswith("6") else "0"
    secid = f"{prefix}.{code}"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": secid,
                "fields": "f43,f62,f64,f184",
            },
            timeout=10,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data")
        if not data:
            return None
        return {
            "price": data.get("f43", 0) / 100 if data.get("f43") else 0,
            "flow_day": data.get("f62") or 0,      # 当日主力净流入 万元
            "flow_pct": data.get("f64") or 0,       # 主力净占比 %
            "flow_5d": data.get("f184") or 0,       # 5日主力净流入 万元
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
    print(f"[START] 主力资金哨兵 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]

    inflow = []    # 5日净流入
    outflow = []   # 5日净流出
    no_data = []

    for i, code in enumerate(codes):
        t = trigger[code]
        name = t.get("name", code)
        d = get_flow(code)
        if i % 3 == 2:
            time.sleep(0.2)

        if not d or d["price"] <= 0:
            no_data.append(name)
            continue

        if d["flow_5d"] > 0:
            inflow.append((name, d["flow_5d"], d["flow_day"], d["flow_pct"]))
        else:
            outflow.append((name, d["flow_5d"], d["flow_day"], d["flow_pct"]))

        print(f"  [{i+1}/{len(codes)}] {name} 5日{d['flow_5d']}万")

    inflow.sort(key=lambda x: -x[1])
    outflow.sort(key=lambda x: x[1])

    lines = [
        f"主力资金哨兵 {now:%m}.{now:%d}",
        f"框架股 5日主力净流入 | {len(codes)-len(no_data)}/{len(codes)}只有数据",
    ]

    if inflow:
        lines.append("")
        lines.append(f"5日净流入 {len(inflow)}只")
        for name, f5, f1, pct in inflow[:10]:
            star = "🔥" if f5 > 10000 else ""
            lines.append(f"  - {star}{name} 5日+{f5/10000:.1f}亿 今日{f1/10000:+.1f}亿 占比{pct:.1f}%")

    if outflow:
        lines.append("")
        lines.append(f"5日净流出 {len(outflow)}只")
        for name, f5, f1, pct in outflow[:8]:
            lines.append(f"  - {name} 5日{f5/10000:.1f}亿 今日{f1/10000:+.1f}亿")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")
        lines.append(f"  {', '.join(no_data[:5])}...")

    lines.append("")
    lines.append(f"> 东财 f184=5日主力净流入 | 🔥=净流入>1亿")

    push(f"主力资金哨兵 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 流入{len(inflow)} 流出{len(outflow)}")


if __name__ == "__main__":
    main()
