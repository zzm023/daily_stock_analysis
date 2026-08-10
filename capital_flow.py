"""
主力资金哨兵 v3
东财资金流日K → 近5日主力净流入自己累加
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_flow_5d(code):
    """东财资金流日K → 返回 (price, flow_5d_sum, 今日占比)"""
    prefix = "1" if code.startswith("6") else "0"
    secid = f"{prefix}.{code}"
    try:
        r = requests.get(
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
            params={
                "secid": secid,
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                "lmt": "5",
            },
            timeout=10,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data")
        if not data or not data.get("klines"):
            return None

        klines = data["klines"]
        flow_5d = 0
        today_flow = 0
        today_pct = 0
        latest_price = 0

        for i, line in enumerate(klines):
            parts = line.split(",")
            if len(parts) < 5:
                continue
            # 格式: 日期,主力净流入,小单净流入,中单净流入,大单净流入,超大单净流入
            try:
                main_flow = float(parts[1]) if parts[1] != "-" else 0
            except:
                main_flow = 0
            flow_5d += main_flow
            if i == len(klines) - 1:
                today_flow = main_flow

        # 取现价
        try:
            r2 = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={"secid": secid, "fields": "f43,f64"},
                timeout=10,
                headers={"Referer": "https://quote.eastmoney.com/"}
            )
            d2 = r2.json().get("data")
            if d2:
                latest_price = d2.get("f43", 0) / 100 if d2.get("f43") else 0
                today_pct = d2.get("f64") or 0
        except:
            pass

        return {
            "price": latest_price,
            "flow_5d": flow_5d,
            "flow_today": today_flow,
            "flow_pct": today_pct,
        }
    except Exception as e:
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
    print(f"[START] 主力资金哨兵 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}

    codes = sorted(held | triggered)
    print(f"  持仓{len(held)} + 已触发{len(triggered)} = {len(codes)}只")

    inflow = []
    outflow = []
    no_data = []

    for i, code in enumerate(codes):
        if code in hold and isinstance(hold.get(code), dict):
            name = hold[code].get("name", code)
        else:
            name = trigger.get(code, {}).get("name", code) if isinstance(trigger.get(code), dict) else code
        tag = "持仓" if code in held else "触发"

        d = get_flow_5d(code)
        if i % 2 == 1:
            time.sleep(0.15)

        if not d or d["price"] <= 0:
            no_data.append(f"{name}({tag})")
            continue

        if d["flow_5d"] > 0:
            inflow.append((name, tag, d["flow_5d"], d["flow_today"], d["flow_pct"]))
        else:
            outflow.append((name, tag, d["flow_5d"], d["flow_today"], d["flow_pct"]))

        print(f"  [{i+1}/{len(codes)}] {name}({tag}) 5日{d['flow_5d']:.0f}万")

    inflow.sort(key=lambda x: -x[2])
    outflow.sort(key=lambda x: x[2])

    lines = [
        f"主力资金哨兵 {now:%m}.{now:%d}",
        f"持仓+已触发 | {len(codes)-len(no_data)}/{len(codes)}只有数据",
    ]

    if inflow:
        lines.append("")
        lines.append(f"近5日净流入 {len(inflow)}只")
        for name, tag, f5, f1, pct in inflow:
            star = "🔥" if f5 > 10000 else ""
            unit5 = "亿" if abs(f5) >= 10000 else "万"
            val5 = f5/10000 if abs(f5) >= 10000 else f5
            unit1 = "亿" if abs(f1) >= 10000 else "万"
            val1 = f1/10000 if abs(f1) >= 10000 else f1
            lines.append(f"  - {star}{name}[{tag}] 5日+{val5:.1f}{unit5} 今日{val1:+.1f}{unit1} 占比{pct:.1f}%")

    if outflow:
        lines.append("")
        lines.append(f"近5日净流出 {len(outflow)}只")
        for name, tag, f5, f1, pct in outflow:
            unit = "亿" if abs(f5) >= 10000 else "万"
            val = f5/10000 if abs(f5) >= 10000 else f5
            lines.append(f"  - {name}[{tag}] 5日{val:.1f}{unit}")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")

    lines.append("")
    lines.append(f"> 东财资金流日K累加 | 🔥=>1亿")

    push(f"主力资金哨兵 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 流入{len(inflow)} 流出{len(outflow)}")


if __name__ == "__main__":
    main()
