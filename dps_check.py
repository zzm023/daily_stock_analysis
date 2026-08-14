#!/usr/bin/env python3
"""
DPS 口径自检（纯 framework_state.json，不需要 Tushare）
判断：dps ÷ 触发价 对比 锚定股息率(anchor_pct)
比率 < 0.7 → 疑似单次（建议全年值 = 触发价 × 锚定股息率）
"""
import os
import json
import requests

STATE_FILE = "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print(content)
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title,
                   "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    except Exception as e:
        print(f"[Push] {e}")


def main():
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    trigger = state.get("trigger", {})

    ok = []
    bad = []

    for code, info in trigger.items():
        if not isinstance(info, dict):
            continue
        dps = info.get("dps", 0)
        anchor = info.get("anchor_pct", 0)
        tp = info.get("trigger_price", 0)
        name = info.get("name", code)
        if not (dps and anchor and tp):
            continue

        implied = dps / tp * 100          # 隐含股息率
        ratio = implied / anchor          # 比率

        if ratio >= 0.7:
            ok.append((name, code, dps, implied, anchor))
        else:
            suggest = round(tp * anchor / 100, 3)   # 建议全年值
            bad.append((name, code, dps, implied, anchor, suggest))

    lines = ["## 🔍 DPS 口径自检", "",
             f"> 判断：dps÷触发价 对比 锚定股息率", ""]

    if bad:
        lines.append(f"### ❌ 疑似单次（需改成全年，{len(bad)}只）")
        lines.append("")
        lines.append("| 股票 | 当前dps | 隐含股息率 | 锚定 | 建议全年值 |")
        lines.append("|------|:--:|:--:|:--:|:--:|")
        for name, code, dps, implied, anchor, suggest in bad:
            lines.append(f"| {name}({code}) | {dps} | {implied:.2f}% | {anchor:.1f}% | **{suggest}** |")
        lines.append("")
    else:
        lines.append("✅ 没有疑似单次的 dps")
        lines.append("")

    if ok:
        lines.append(f"### ✅ 正常（全年口径，{len(ok)}只）")
        lines.append("")
        for name, code, dps, implied, anchor in ok:
            lines.append(f"- {name}({code}) dps {dps}（隐含 {implied:.2f}% / 锚定 {anchor:.1f}%）")
        lines.append("")

    lines.append("---")
    lines.append("建议值 = 触发价 × 锚定股息率（近似，精确值以年报为准）")

    push("DPS口径自检", "\n".join(lines))
    print("完成")


if __name__ == "__main__":
    main()
