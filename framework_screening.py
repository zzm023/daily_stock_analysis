"""
框架全量筛选表 v2
批量取价 + 纯文本格式 PushPlus 友好
每周一推送
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_get_prices(codes):
    """腾讯批量取价：每批40只"""
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(
            f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch
        )
        try:
            r = requests.get(
                f"http://qt.gtimg.cn/q={symbols}", timeout=15
            )
            r.encoding = "gbk"
            for line in r.text.strip().split("\n"):
                if "=" not in line or '""' in line:
                    continue
                code = line.split("_")[-1].split("=")[0].replace("sh","").replace("sz","")
                parts = line.split("~")
                if len(parts) >= 4 and parts[3]:
                    prices[code] = float(parts[3])
        except Exception as e:
            print(f"  批量取价失败: {e}")
    return prices


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
    print(f"[START] 框架筛选 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    # 批量取价
    all_codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    print(f"  批量取价 {len(all_codes)} 只 ...")
    prices = batch_get_prices(all_codes)
    print(f"  获取到 {len(prices)} 只价格")

    lines = [
        f"## 📊 框架全量筛选 — {now:%Y.%m.%d}",
        "",
        f"{now:%H:%M} | 框架股{len(all_codes)}只 | 价格为腾讯实时",
        "",
    ]

    # 分组
    approaching = []    # gap ≤ 10%
    mid_range = []      # gap 10-30%
    far_away = []       # gap > 30%

    for code, t in trigger.items():
        if not isinstance(t, dict):
            continue

        name = t.get("name", code)
        target = t.get("trigger_price", 0)
        status = t.get("status", "远离")
        resonance = t.get("resonance", "")
        pe_now = t.get("pe_now", 0)
        pb_now = t.get("pb_now", 0)
        price = prices.get(code, 0)

        gap = round((price - target) / target * 100, 1) if price and target else 0
        held = "🔴" if code in hold and isinstance(hold.get(code), dict) else ""

        entry = {
            "name": name, "code": code, "price": price, "target": target,
            "gap": gap, "pe": pe_now, "pb": pb_now,
            "resonance": resonance, "held": held, "status": status,
        }

        if status == "已触发" or (gap and gap <= 10):
            approaching.append(entry)
        elif gap and gap <= 30:
            mid_range.append(entry)
        else:
            far_away.append(entry)

    # ── 输出 ──
    if approaching:
        lines.append("### 🎯 接近触发 / 已触发")
        lines.append("")
        approaching.sort(key=lambda x: x["gap"] if x["gap"] > -99 else -99)
        for e in approaching:
            p_s = f"现{e['price']:.2f}" if e["price"] else "现?"
            g_s = f"距{e['gap']:.1f}%" if e["gap"] else "?"
            pe_s = f"PE{e['pe']:.1f}" if e["pe"] else ""
            pb_s = f"PB{e['pb']:.2f}" if e["pb"] else ""
            r_s = "⚡双振" if "双振" in e["resonance"] else "🎯已触发" if e["status"] == "已触发" else ""
            lines.append(
                f"**{e['name']}** {p_s} 触发{e['target']:.2f} {g_s} {pe_s} {pb_s} {r_s} {e['held']}"
            )
            lines.append("")
    else:
        lines.append("### 🎯 接近触发")
        lines.append("无。")
        lines.append("")

    if mid_range:
        lines.append("### 🔸 中等距离（10-30%）")
        lines.append("")
        mid_range.sort(key=lambda x: x["gap"])
        for e in mid_range[:15]:
            p_s = f"现{e['price']:.2f}" if e["price"] else "现?"
            g_s = f"距{e['gap']:.1f}%"
            r_s = "⚡" if "双振" in e["resonance"] else ""
            lines.append(
                f"**{e['name']}** {p_s} 触发{e['target']:.2f} {g_s} {r_s} {e['held']}"
            )
            lines.append("")
        if len(mid_range) > 15:
            lines.append(f"> 另有{len(mid_range)-15}只略。")
            lines.append("")

    if far_away:
        lines.append("### 🔹 远离（>30%）")
        lines.append("")
        held_away = [e for e in far_away if e["held"]]
        if held_away:
            lines.append("仅列出持仓：")
            for e in held_away:
                lines.append(f"- **{e['name']}** 现{e['price']:.2f} 触发{e['target']:.2f}")
            lines.append("")
        lines.append(f"> 其余{len(far_away)-len(held_away)}只省略。")

    lines.append("---")
    lines.append(f"📌 每周一推送。⚡双振=估值确认 | 🔴=持仓")

    push(f"📊 框架筛选 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(all_codes)}只")


if __name__ == "__main__":
    main()
