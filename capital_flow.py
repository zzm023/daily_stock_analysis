"""
主力资金哨兵 v4
腾讯 ff_ 接口 → 每日存 state → 5日自己累
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_today_flow(codes):
    """腾讯 ff_ 批量 → {code: main_net_flow_万元}"""
    result = {}
    symbols = ",".join(f"ff_{'sh' if c.startswith('6') else 'sz'}{c}" for c in codes)
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
        r.encoding = "gbk"
        text = r.text
        for c in codes:
            prefix = "sh" if c.startswith("6") else "sz"
            m = re.search(f"v_ff_{prefix}{c}=\"[^\"]*\"", text)
            if not m:
                continue
            parts = m.group().split("~")
            # 格式: code,主力流入,主力流出,主力净流入,净占比,...
            if len(parts) >= 5:
                try:
                    net = float(parts[4]) if parts[4] else 0  # 万元
                    result[c] = net
                except:
                    pass
    except Exception as e:
        print(f"  ff_ 失败: {e}")
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
    today = now.strftime("%Y-%m-%d")
    print(f"[START] 主力资金哨兵 v4 {today}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}

    codes = sorted(held | triggered)
    print(f"  持仓{len(held)} + 触发{len(triggered)} = {len(codes)}只")

    flows = get_today_flow(codes)
    print(f"  获取 {len(flows)} 只资金数据")

    # 读/写历史
    flow_hist = state.setdefault("flow_history", {})

    inflow = []
    outflow = []
    no_data = []

    for code in codes:
        if code in hold and isinstance(hold.get(code), dict):
            name = hold[code].get("name", code)
        else:
            name = trigger.get(code, {}).get("name", code) if isinstance(trigger.get(code), dict) else code
        tag = "持仓" if code in held else "触发"

        today_flow = flows.get(code)
        if today_flow is None:
            no_data.append(f"{name}({tag})")
            continue

        # 存历史（保留最近 10 天）
        hist = flow_hist.setdefault(code, [])
        hist.append({"date": today, "flow": today_flow})
        if len(hist) > 10:
            hist = hist[-10:]
        flow_hist[code] = hist

        # 算 5 日累计
        recent = hist[-5:]
        flow_5d = sum(d["flow"] for d in recent)
        days = len(recent)

        if flow_5d > 0:
            inflow.append((name, tag, flow_5d, today_flow, days))
        else:
            outflow.append((name, tag, flow_5d, today_flow, days))

        print(f"  {name}({tag}) 今日{today_flow:.0f}万 5日{flow_5d:.0f}万")

    state["flow_history"] = flow_hist
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    inflow.sort(key=lambda x: -x[2])
    outflow.sort(key=lambda x: x[2])

    lines = [
        f"主力资金哨兵 {now:%m}.{now:%d}",
        f"持仓+已触发 | {len(codes)-len(no_data)}/{len(codes)}只有数据",
    ]

    if inflow:
        lines.append("")
        lines.append(f"5日净流入 {len(inflow)}只")
        for name, tag, f5, f1, days in inflow:
            star = "🔥" if f5 > 10000 else ""
            unit5 = "亿" if abs(f5) >= 10000 else "万"
            val5 = f5/10000 if abs(f5) >= 10000 else f5
            unit1 = "亿" if abs(f1) >= 10000 else "万"
            val1 = f1/10000 if abs(f1) >= 10000 else f1
            lines.append(f"  - {star}{name}[{tag}] {days}日+{val5:.1f}{unit5} 今日{val1:+.1f}{unit1}")

    if outflow:
        lines.append("")
        lines.append(f"5日净流出 {len(outflow)}只")
        for name, tag, f5, f1, days in outflow:
            unit = "亿" if abs(f5) >= 10000 else "万"
            val = f5/10000 if abs(f5) >= 10000 else f5
            lines.append(f"  - {name}[{tag}] {days}日{val:.1f}{unit}")

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")

    lines.append("")
    lines.append(f"> 腾讯 ff_ 接口 | 历史自累 | 首跑仅1日数据")

    push(f"主力资金哨兵 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 流入{len(inflow)} 流出{len(outflow)}")


if __name__ == "__main__":
    main()
