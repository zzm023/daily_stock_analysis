"""
主力资金哨兵 v2
只监控：持仓股 + 已触发股票
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_flow(code):
    prefix = "1" if code.startswith("6") else "0"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": f"{prefix}.{code}", "fields": "f43,f62,f64,f184"},
            timeout=10,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data")
        if not data or not data.get("f43"):
            return None
        return {
            "price": data["f43"] / 100,
            "flow_day": data.get("f62") or 0,
            "flow_pct": data.get("f64") or 0,
            "flow_5d": data.get("f184") or 0,
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
    print(f"[START] 主力资金哨兵 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    # 持仓股代码
    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    # 已触发股票代码
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}

    codes = sorted(held | triggered)
    print(f"  持仓{len(held)} + 已触发{len(triggered)} = {len(codes)}只")

    inflow = []
    outflow = []
    no_data = []

    for i, code in enumerate(codes):
        # 确定名称
        if code in hold and isinstance(hold.get(code), dict):
            name = hold[code].get("name", code)
        elif code in trigger and isinstance(trigger.get(code), dict):
            name = trigger[code].get("name", code)
        else:
            name = code

        tag = "持仓" if code in held else "触发"

        d = get_flow(code)
        if i % 3 == 2:
            time.sleep(0.2)

        if not d:
            no_data.append(f"{name}({tag})")
            continue

        if d["flow_5d"] > 0:
            inflow.append((name, tag, d["flow_5d"], d["flow_day"], d["flow_pct"]))
        else:
            outflow.append((name, tag, d["flow_5d"], d["flow_day"], d["flow_pct"]))

        print(f"  [{i+1}/{len(codes)}] {name}({tag}) 5日{d['flow_5d']}万")

    inflow.sort(key=lambda x: -x[2])
    outflow.sort(key=lambda x: x[2])

    lines = [
        f"主力资金哨兵 {now:%m}.{now:%d}",
        f"持仓+已触发 | {len(codes)-len(no_data)}/{len(codes)}只有数据",
    ]

    if inflow:
        lines.append("")
        lines.append(f"5日净流入 {len(inflow)}只")
        for name, tag, f5, f1, pct in inflow:
            star = "🔥" if f5 > 10000 else ""
            unit = "亿" if abs(f5) >= 10000 else "万"
            val = f5/10000 if abs(f5) >= 10000 else f5
            val1 = f1/10000 if abs(f1) >= 10000 else f1
            unit1 = "亿" if abs(f1) >= 10000 else "万"
            lines.append(f"  - {star}{name}[{tag}] 5日+{val:.1f}{unit} 今日{val1:+.1f}{unit1} 占比{pct:.1f}%")

    if outflow:
        lines.append("")
        lines.append(f"5日净流出 {len(outflow)}只")
        for name, tag, f5, f1, pct in outflow:
            unit = "亿" if abs(f5) >= 10000 else "万"
            val = f5/10000 if abs(f5) >= 10000 else f5
            lines.append(f"  - {name}[{tag}] 5日{val:.1f}{unit}")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")
        lines.append(f"  {', '.join(no_data[:5])}")

    lines.append("")
    lines.append(f"> 东财 f184=5日主力净流入(万元) | 🔥=>1亿")

    push(f"主力资金哨兵 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 流入{len(inflow)} 流出{len(outflow)}")


if __name__ == "__main__":
    main()
