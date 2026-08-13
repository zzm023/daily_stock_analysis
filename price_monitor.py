"""
触发价监控（收盘后 15:45）
读 framework_state.json 触发价（单一数据源），检查是否触及/接近触发价
与价格异动监控共用 framework_state.json，自动同步清除目录和触发价调整
"""

import os, json, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"

GAP_CLOSE = 10.0   # 即将触发：gap ≤ 10%


def to_secid(code):
    if code.startswith(("6", "9")):
        return "1." + code
    return "0." + code


def load_framework():
    """读 framework_state.json → (trigger价dict, 持仓dict)"""
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}, {}
    trigger = data.get("trigger", {})
    holdings = {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}
    return trigger, holdings


def fetch_prices(secids):
    """东财批量实时价（收盘后即收盘价）"""
    url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"secids": ",".join(secids), "fields": "f2,f12,f14"}
    try:
        r = requests.get(url, params=params, timeout=10)
        return r.json().get("data", {}).get("diff", [])
    except Exception as e:
        print(f"  [东财] {e}")
        return []


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        r = requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title,
            "content": content, "template": "markdown",
            "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
        print(f"  [Push] {'OK' if r.json().get('code') == 200 else r.json()}")
    except Exception as e:
        print(f"  [Push] {e}")


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 触发价监控 {now:%m-%d %H:%M}")

    trigger, holdings = load_framework()
    hold_codes = set(holdings.keys())

    # 候选：trigger_price > 0 的股票
    candidates = []
    for code, info in trigger.items():
        tp = info.get("trigger_price", 0) or 0
        if tp <= 0:
            continue
        candidates.append({
            "code": code,
            "name": info.get("name", code),
            "trigger": tp,
            "attr": info.get("anchor_pct", 0),
            "is_hold": code in hold_codes,
        })

    if not candidates:
        push(f"📊 触发价监控 {now:%m-%d}", "## 触发价监控\n\nframework_state.json 无有效触发价。")
        return

    # 批量拉价
    secids = [to_secid(c["code"]) for c in candidates]
    quotes = fetch_prices(secids)

    price_map = {}
    for q in quotes:
        code = q.get("f12", "")
        try:
            price = float(q.get("f2", 0))
        except:
            price = 0
        if price > 0:
            price_map[code] = price

    hit = []    # 已触发：现价 ≤ 触发价
    close = []  # 即将：gap ≤ 10%
    failed = 0

    for c in candidates:
        code = c["code"]
        price = price_map.get(code)
        if price is None:
            failed += 1
            continue

        gap_pct = (price - c["trigger"]) / c["trigger"] * 100

        if price <= c["trigger"]:
            hit.append({**c, "price": price, "gap": gap_pct})
        elif gap_pct <= GAP_CLOSE:
            close.append({**c, "price": price, "gap": gap_pct})

    print(f"  已触发 {len(hit)} 只 | 即将 {len(close)} 只 | 失败 {failed} 只")

    if not hit and not close:
        print("[DONE] 无触发/即将触发，不推送")
        return

    lines = [
        f"## 📊 触发价监控 {now:%m-%d %H:%M}",
        f"监控 {len(candidates)} 只（framework_state.json）",
        "",
    ]

    if hit:
        lines.append("### 🔥 已触发（现价 ≤ 触发价）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 | 备注 |")
        lines.append("|------|------|--------|------|------|")
        for c in hit:
            tag = "持仓·补仓" if c["is_hold"] else "待买"
            lines.append(f"| {c['name']}({c['code']}) | {c['price']:.2f} | {c['trigger']:.2f} | {c['gap']:+.1f}% | {tag} |")
        lines.append("")

    if close:
        lines.append("### ⏳ 即将触发（距触发 ≤10%）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 | 备注 |")
        lines.append("|------|------|--------|------|------|")
        for c in close:
            tag = "持仓·补仓" if c["is_hold"] else "待买"
            lines.append(f"| {c['name']}({c['code']}) | {c['price']:.2f} | {c['trigger']:.2f} | {c['gap']:+.1f}% | {tag} |")
        lines.append("")

    lines.append("> ⚠️ 触发 ≠ 立即买。左侧分层：目标价打9折、仓位减半、观察1周。")

    push(f"📊 触发价监控（{len(hit)}触发/{len(close)}临近）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
