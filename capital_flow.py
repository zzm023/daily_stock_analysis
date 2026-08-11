"""
主力资金哨兵 v7
交易时段取 f62 + 存历史自累5日 → 非交易时段读缓存
"""
import os, json, requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_today_flow(code):
    """东财单只 f62=主力净流入(元) → 返回元"""
    prefix = "1" if code.startswith("6") else "0"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": f"{prefix}.{code}", "fields": "f43,f62,f64"},
            timeout=10,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        d = r.json().get("data")
        if not d or d.get("f62") is None:
            return None
        return {
            "price": d.get("f43", 0) / 100 if d.get("f43") else 0,
            "flow": d["f62"],  # 元
            "pct": d.get("f64") or 0,
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
    today = now.strftime("%Y-%m-%d")
    print(f"[START] 主力资金哨兵 v7 {today}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}
    codes = sorted(held | triggered)

    flow_hist = state.setdefault("flow_history", {})
    new_data = 0

    inflow = []
    outflow = []
    no_update = []

    for code in codes:
        if code in hold and isinstance(hold.get(code), dict):
            name = hold[code].get("name", code)
        else:
            name = trigger.get(code, {}).get("name", code) if isinstance(trigger.get(code), dict) else code
        tag = "持仓" if code in held else "触发"

        # 取今日
        d = get_today_flow(code)
        hist = flow_hist.get(code, [])

        if d and d["flow"] is not None:
            # 去重：同日不重复存
            if not hist or hist[-1].get("date") != today:
                hist.append({"date": today, "flow": d["flow"]})
                new_data += 1
            flow_hist[code] = hist[-10:]  # 保留最近10天
        else:
            no_update.append(f"{name}({tag})")

        # 算5日累计（用最近5条）
        recent = hist[-5:]
        flow_5d = sum(h["flow"] for h in recent)

        if flow_5d > 0:
            inflow.append((name, tag, flow_5d, d["flow"] if d else 0, d["pct"] if d else 0))
        else:
            outflow.append((name, tag, flow_5d, d["flow"] if d else 0, d["pct"] if d else 0))

    # 保存
    state["flow_history"] = flow_hist
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    inflow.sort(key=lambda x: -x[2])
    outflow.sort(key=lambda x: x[2])

    lines = [
        f"主力资金哨兵 {now:%m}.{now:%d}",
        f"持仓+已触发 {len(codes)}只 | 今日新取{new_data}只",
    ]

    if inflow:
        lines.append("")
        lines.append(f"5日净流入 {len(inflow)}只")
        for name, tag, f5, f1, pct in inflow:
            star = "🔥" if f5 > 100000000 else ""
            val5 = f5 / 100000000
            val1 = f1 / 100000000
            lines.append(f"  - {star}{name}[{tag}] 5日{val5:+.1f}亿 今日{val1:+.2f}亿 占比{pct:.1f}%")

    if outflow:
        lines.append("")
        lines.append(f"5日净流出 {len(outflow)}只")
        for name, tag, f5, f1, pct in outflow:
            val5 = f5 / 100000000
            lines.append(f"  - {name}[{tag}] 5日{val5:.1f}亿")

    if no_update:
        lines.append("")
        lines.append(f"今日无新数据 {len(no_update)}只（非交易时段正常）")

    lines.append("")
    lines.append(f"> 东财 f62 | 15:30后跑有数据 | 缓存自累5日")

    push(f"主力资金哨兵 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 新取{new_data} 流入{len(inflow)} 流出{len(outflow)}")


if __name__ == "__main__":
    main()
