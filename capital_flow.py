"""
主力资金哨兵 v6
东财 clist 直传 secids → 绝不漏
"""
import os, json, requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_flow_by_codes(codes):
    """东财 clist 直接传 secids → {code: {flow_5d, flow_today, flow_pct}}"""
    secids = ",".join(f"1.{c}" if c.startswith("6") else f"0.{c}" for c in codes)
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "secids": secids,
                "pn": 1, "pz": 50,
                "fltt": 2, "invt": 2,
                "fields": "f2,f12,f14,f62,f64,f184",
            },
            timeout=15,
            headers={"Referer": "https://data.eastmoney.com/"}
        )
        data = r.json().get("data")
        if not data or not data.get("diff"):
            return {}
        result = {}
        for item in data["diff"]:
            code = item.get("f12", "")
            if not code:
                continue
            result[code] = {
                "name": item.get("f14", code),
                "price": item.get("f2", 0) or 0,
                "flow_today": item.get("f62") or 0,
                "flow_pct": item.get("f64") or 0,
                "flow_5d": item.get("f184") or 0,
            }
        return result
    except Exception as e:
        print(f"  secids请求失败: {e}")
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
    print(f"[START] 主力资金哨兵 v6 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}
    codes = sorted(held | triggered)

    print(f"  目标 {len(codes)} 只，secids 直查...")
    all_data = get_flow_by_codes(codes)
    print(f"  返回 {len(all_data)} 只")

    inflow = []
    outflow = []
    no_data = []

    for code in codes:
        if code in hold and isinstance(hold.get(code), dict):
            name = hold[code].get("name", code)
        else:
            name = trigger.get(code, {}).get("name", code) if isinstance(trigger.get(code), dict) else code
        tag = "持仓" if code in held else "触发"

        d = all_data.get(code)
        if not d:
            no_data.append(f"{name}({tag})")
            continue

        if d["flow_5d"] > 0:
            inflow.append((name, tag, d["flow_5d"], d["flow_today"], d["flow_pct"]))
        else:
            outflow.append((name, tag, d["flow_5d"], d["flow_today"], d["flow_pct"]))

    inflow.sort(key=lambda x: -x[2])
    outflow.sort(key=lambda x: x[2])

    lines = [
        f"主力资金哨兵 {now:%m}.{now:%d}",
        f"持仓+已触发 | {len(codes)-len(no_data)}/{len(codes)}只",
    ]

    if inflow:
        lines.append("")
        lines.append(f"5日净流入 {len(inflow)}只")
        for name, tag, f5, f1, pct in inflow:
            star = "🔥" if abs(f5) > 100000000 else ""
            val5 = f5 / 100000000
            val1 = f1 / 100000000
            lines.append(f"  - {star}{name}[{tag}] 5日{val5:+.1f}亿 今日{val1:+.1f}亿 占比{pct:.2f}%")

    if outflow:
        lines.append("")
        lines.append(f"5日净流出 {len(outflow)}只")
        for name, tag, f5, f1, pct in outflow:
            val5 = f5 / 100000000
            lines.append(f"  - {name}[{tag}] 5日{val5:.1f}亿")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")
        lines.append(f"  {', '.join(no_data[:5])}")

    lines.append("")
    lines.append(f"> 东财 secids 直查")

    push(f"主力资金哨兵 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 流入{len(inflow)} 流出{len(outflow)}")


if __name__ == "__main__":
    main()
