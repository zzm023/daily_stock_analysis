"""
框架全量筛选表 v1
52只框架股票：现价/触发价/差距/PE/PB/共振/属性/持仓
每周一推送
"""
import os
import json
import requests
from datetime import datetime, date
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_price(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) >= 4 and parts[3]:
            return float(parts[3])
    except:
        pass
    return 0


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
    print(f"[START] 框架筛选表 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    lines = [f"## 📊 框架全量筛选 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 框架股52只 | 追踪关键位", "",
             "| # | 股票 | 代码 | 现价 | 触发 | 差距 | PE | PB | 共振 | 持仓 |",
             "|---|------|------|------|------|------|----|----|------|------|"]

    rows = []
    for code, t in trigger.items():
        if not isinstance(t, dict):
            continue

        name = t.get("name", code)
        target = t.get("trigger_price", 0)
        pe_upper = t.get("pe_upper", 0)
        pb_lower = t.get("pb_lower", 0)
        status = t.get("status", "远离")
        resonance = t.get("resonance", "")
        attr = t.get("attr", "")

        price = get_price(code)
        if not price and target:
            price = t.get("price_now", 0)

        gap = round((price - target) / target * 100, 1) if price and target else 0

        # 实时 PE/PB
        pe_now = t.get("pe_now", 0)
        pb_now = t.get("pb_now", 0)

        # 是否持仓
        held = "🔴" if code in hold and isinstance(hold.get(code), dict) else ""

        # 共振标记
        r_tag = ""
        if "双振" in resonance:
            r_tag = "⚡"
        elif status == "已触发":
            r_tag = "🎯"
        elif status == "接近":
            r_tag = "🔹"

        rows.append({
            "name": name, "code": code, "price": price, "target": target,
            "gap": gap, "pe": pe_now, "pb": pb_now,
            "r_tag": r_tag, "held": held, "status": status,
            "pe_upper": pe_upper, "pb_lower": pb_lower,
        })

    # 排序：距触发价最近 → 最远
    rows.sort(key=lambda x: x["gap"] if x["gap"] > -99 else -99)

    for i, r in enumerate(rows, 1):
        price_s = f"{r['price']:.2f}" if r['price'] else "?"
        target_s = f"{r['target']:.2f}" if r['target'] else "?"
        gap_s = f"{r['gap']:.1f}%" if r['gap'] else "?"
        pe_s = f"{r['pe']:.1f}" if r['pe'] else "?"
        pb_s = f"{r['pb']:.2f}" if r['pb'] else "?"

        tag = r["r_tag"]
        if r["held"]:
            tag += "🔴" if not r["r_tag"] else ""

        lines.append(
            f"| {i} | {r['name']} | {r['code']} | {price_s} | "
            f"{target_s} | {gap_s} | {pe_s} | {pb_s} | {tag} | {r['held']} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("⚡双振 | 🎯已触发 | 🔹接近 | 🔴持仓")
    lines.append(f"📌 筛选逻辑：距触发价≤10% + 双振 = 优先关注。每周一推送。")

    push(f"📊 框架筛选 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(rows)}只已筛选")


if __name__ == "__main__":
    main()
