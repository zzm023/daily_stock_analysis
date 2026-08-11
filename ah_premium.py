"""
AH溢价监控 v2
未持仓溢价>50%提示H股 | 持仓股跳过 | 仅框架内AH
"""
import os
import json
import requests
import re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# A股代码 → 腾讯H股代码（核实过）
AH_PAIRS = {
    "600031": "hk00631",  # 三一重工
    "601601": "hk02601",  # 中国太保
    "600585": "hk00914",  # 海螺水泥
    "600188": "hk01171",  # 兖矿能源
    "600660": "hk03606",  # 福耀玻璃
    "600036": "hk03968",  # 招商银行
    "600941": "hk00941",  # 中国移动
    "000333": "hk00300",  # 美的集团
    "688187": "hk03898",  # 时代电气
}


def batch_ah(pairs):
    """腾讯批量取股价"""
    all_ids = []
    for a, h in pairs.items():
        all_ids.append(f"sh{a}" if a.startswith("6") else f"sz{a}")
        all_ids.append(h)

    results = {}
    for i in range(0, len(all_ids), 40):
        batch = all_ids[i:i + 40]
        symbols = ",".join(batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for sid in batch:
                m = re.search(f"v_{sid}=\"[^\"]*\"", r.text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 4:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    name = parts[1] if len(parts) > 1 else sid
                    if price and price > 0:
                        results[sid] = {"price": price, "name": name}
                except Exception:
                    pass
        except Exception:
            pass
    return results


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        requests.post(
            "http://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown",
                "topic": PUSHPLUS_TOPIC,
            },
            timeout=10
        )
    except Exception:
        pass


def main():
    now = datetime.now()
    print(f"[START] AH溢价监控 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    # 只查框架内的 AH 对
    active = {}
    for a_code, h_code in AH_PAIRS.items():
        if a_code in trigger:
            active[a_code] = h_code

    all_ids = {}
    for a, h in active.items():
        all_ids[a] = f"sh{a}" if a.startswith("6") else f"sz{a}"
    quotes = batch_ah(active)
    print(f"  行情 {len(quotes)} 只")

    held_skip = []
    suggest_h = []
    normal = []
    no_data = []

    for a_code, h_code in active.items():
        a_sid = f"sh{a_code}" if a_code.startswith("6") else f"sz{a_code}"
        a_q = quotes.get(a_sid)
        h_q = quotes.get(h_code)
        if not a_q or not h_q:
            t = trigger.get(a_code, {})
            name = t.get("name", a_code) if isinstance(t, dict) else a_code
            no_data.append(name)
            continue

        a_price = a_q["price"]
        h_price = h_q["price"]
        premium = (a_price - h_price) / h_price * 100 if h_price > 0 else None
        if premium is None:
            continue

        t = trigger.get(a_code, {})
        name = t.get("name", a_code) if isinstance(t, dict) else a_code
        is_held = a_code in hold

        if is_held:
            held_skip.append(name)
        elif premium > 50:
            suggest_h.append({
                "name": name, "a_price": a_price, "h_price": h_price,
                "premium": premium,
            })
        else:
            normal.append({
                "name": name, "a_price": a_price, "h_price": h_price,
                "premium": premium,
            })

    lines = [
        f"AH溢价监控 {now:%m}.{now:%d}",
        f"同股同权A/H比价 | 框架内{len(active)}对",
    ]

    if held_skip:
        lines.append("")
        lines.append(f"持仓（不显示溢价）{len(held_skip)}只")
        lines.append(f"  {', '.join(held_skip)}")

    if suggest_h:
        lines.append("")
        lines.append(f"🔄 A溢价>50% 买H更划算（{len(suggest_h)}只）")
        for r in suggest_h:
            lines.append(
                f"- {r['name']} A{r['a_price']:.2f} H{r['h_price']:.2f} "
                f"溢价{r['premium']:+.0f}%"
            )

    if normal:
        lines.append("")
        lines.append(f"溢价正常 ≤50%（{len(normal)}只）")
        for r in normal:
            lines.append(
                f"- {r['name']} A{r['a_price']:.2f} H{r['h_price']:.2f} "
                f"溢价{r['premium']:+.0f}%"
            )

    if no_data:
        lines.append("")
        lines.append(f"无数据 {len(no_data)}只")
        lines.append(f"  {', '.join(no_data)}")

    if not suggest_h and not normal:
        lines.append("")
        lines.append("无有效数据，检查AH配对代码")

    push(f"AH溢价 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 建议H股{len(suggest_h)}只")


if __name__ == "__main__":
    main()
