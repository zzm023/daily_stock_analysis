"""
观察清单自动分类 v3 - Tushare+腾讯
"""
import os, json, requests, re, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title, "content": content,
            "template": "markdown", "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
    except: pass


def _to_ts_code(code):
    if "." in code: return code
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def classify_stock(t):
    trigger_price = t.get("trigger_price", 0)
    pe_upper = t.get("pe_upper", 20)
    pb_lower = t.get("pb_lower", 2)

    if trigger_price <= 0:
        return "8_清除"
    if pe_upper > 25 or pb_lower > 4:
        return "6_战略观察"
    return "7_战术观察"


def main():
    now = datetime.now()
    print(f"[START] 分类 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]

    # ── 行情 ──
    quotes = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i+30]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if not m: continue
                parts = m.group().split("~")
                if len(parts) < 48: continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    if price: quotes[c] = {"price": price, "pe": pe}
                except: pass
        except: pass

    strategic = []
    tactical = []
    cleared = []

    for code in codes:
        t = trigger[code]
        tag = classify_stock(t)
        t["tag"] = tag

        if "6_" in tag:
            strategic.append(code)
        elif "8_" in tag:
            cleared.append(code)
        else:
            tactical.append(code)

    # 更新现价
    for code in quotes:
        if code in trigger and isinstance(trigger[code], dict):
            trigger[code]["current_price"] = quotes[code]["price"]

    state["meta"]["updated"] = now.isoformat()
    state["trigger"] = trigger

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ── 推送 ──
    lines = [f"观察清单分类 {now:%m}.{now:%d}"]
    if strategic:
        lines.append(f"🔵 战略观察 {len(strategic)}只")
        for c in strategic[:10]:
            lines.append(f"  - {trigger[c]['name']}")
        if len(strategic) > 10:
            lines.append(f"  - ...等{len(strategic)-10}只")
    if tactical:
        lines.append(f"🟡 战术观察 {len(tactical)}只")
        for c in tactical[:10]:
            lines.append(f"  - {trigger[c]['name']}")
        if len(tactical) > 10:
            lines.append(f"  - ...等{len(tactical)-10}只")
    if cleared:
        lines.append(f"🔴 清除 {len(cleared)}只")
        for c in cleared[:5]:
            lines.append(f"  - {trigger[c]['name']}")

    lines.append(f"> 共{len(codes)}只")

    push(f"分类 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 战略{len(strategic)} 战术{len(tactical)} 清除{len(cleared)}")


if __name__ == "__main__":
    main()
