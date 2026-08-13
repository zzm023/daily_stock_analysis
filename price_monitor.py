"""
触发价总监控 v1.0（任务①）
功能：已触发 + 即将触发 + 买入清单 + 距触发价排行
数据源：framework_state.json（触发价/PE/PB锚点/持仓） + 东财实时价(收盘价)
联动：买入清单 = gap≤10% + PE≤pe_upper + PB≤pb_lower（锚点严格取框架，不猜测）
运行：收盘后 15:45
"""

import os, json, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"

GAP_CLOSE = 10.0   # 即将触发：gap ≤ 10%
RANK_TOP = 10      # 距触发价排行前 N 名


def to_secid(code):
    if code.startswith(("6", "9")):
        return "1." + code
    return "0." + code


def load_framework():
    """读 framework_state.json → (trigger, holdings)"""
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}, {}
    trigger = data.get("trigger", {})
    holdings = {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}
    return trigger, holdings


def fetch_quotes(secids):
    """东财批量：f2现价 f9市盈率 f23市净率"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"secids": ",".join(secids), "fields": "f2,f9,f12,f14,f23"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    r = None
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get("data", {}).get("diff", [])
    except Exception as e:
        snippet = repr(r.text[:200]) if r is not None else ""
        print(f"  [东财] {e} | 响应: {snippet}")
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
    print(f"[START] 触发价总监控 {now:%m-%d %H:%M}")

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
            "pe_upper": info.get("pe_upper", 0) or 0,
            "pb_lower": info.get("pb_lower", 0) or 0,
            "is_hold": code in hold_codes,
        })

    if not candidates:
        push(f"📊 触发价总监控 {now:%m-%d}", "## 触发价总监控\n\nframework_state.json 无有效触发价。")
        return

    secids = [to_secid(c["code"]) for c in candidates]
    quotes = fetch_quotes(secids)
    if not quotes:
        print("[SKIP] 行情为空")
        return

    # 解析行情
    quote_map = {}
    for q in quotes:
        code = q.get("f12", "")
        try:
            price = float(q.get("f2", 0))
            pe = float(q.get("f9", 0))
            pb = float(q.get("f23", 0))
        except:
            price = pe = pb = 0
        if code:
            quote_map[code] = {"price": price, "pe": pe, "pb": pb}

    hit = []     # 已触发：现价 ≤ 触发价
    close = []   # 即将：gap ≤ 10%
    buy = []     # 买入清单：gap≤10% + PE/PB达标
    ranking = [] # 距触发价排行

    for c in candidates:
        code = c["code"]
        q = quote_map.get(code)
        if q is None:
            continue
        price = q["price"]
        if price <= 0:
            continue

        gap = (price - c["trigger"]) / c["trigger"] * 100
        row = {**c, "price": price, "gap": gap, "pe": q["pe"], "pb": q["pb"]}
        ranking.append(row)

        if price <= c["trigger"]:
            hit.append(row)
        elif gap <= GAP_CLOSE:
            close.append(row)
            # 买入清单判断：PE/PB 锚点都存在且达标
            if c["pe_upper"] > 0 and c["pb_lower"] > 0 and q["pe"] > 0 and q["pb"] > 0:
                if q["pe"] <= c["pe_upper"] and q["pb"] <= c["pb_lower"]:
                    buy.append(row)

    # 距触发价排行（升序）
    ranking.sort(key=lambda x: x["gap"])

    print(f"  已触发 {len(hit)} | 临近 {len(close)} | 买入清单 {len(buy)}")

    # 推送
    lines = [
        f"## 📊 触发价总监控 {now:%m-%d %H:%M}",
        f"监控 {len(candidates)} 只 · 已触发 {len(hit)} · 临近 {len(close)} · 可买 {len(buy)}",
        "",
    ]

    if hit:
        lines.append("### 🔥 已触发（现价≤触发价）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 | 备注 |")
        lines.append("|:--|--:|--:|--:|:--|")
        for r in hit:
            tag = "持仓·补仓" if r["is_hold"] else "待买"
            lines.append(f"| {r['name']}({r['code']}) | {r['price']:.2f} | {r['trigger']:.2f} | {r['gap']:+.1f}% | {tag} |")
        lines.append("")

    if buy:
        lines.append("### 🎯 买入清单（gap≤10% + PE/PB达标）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 | PE | PB |")
        lines.append("|:--|--:|--:|--:|--:|--:|")
        for r in buy:
            lines.append(f"| {r['name']}({r['code']}) | {r['price']:.2f} | {r['trigger']:.2f} | {r['gap']:+.1f}% | {r['pe']:.1f} | {r['pb']:.2f} |")
        lines.append("")

    if close:
        lines.append("### ⏳ 即将触发（距触发≤10%，未达估值）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 | PE | PB |")
        lines.append("|:--|--:|--:|--:|--:|--:|")
        for r in close:
            if any(b["code"] == r["code"] for b in buy):
                continue  # 已在买入清单，跳过
            lines.append(f"| {r['name']}({r['code']}) | {r['price']:.2f} | {r['trigger']:.2f} | {r['gap']:+.1f}% | {r['pe']:.1f} | {r['pb']:.2f} |")
        lines.append("")

    if ranking:
        lines.append(f"### 📉 距触发价排行（前{RANK_TOP}）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 |")
        lines.append("|:--|--:|--:|--:|")
        for r in ranking[:RANK_TOP]:
            lines.append(f"| {r['name']}({r['code']}) | {r['price']:.2f} | {r['trigger']:.2f} | {r['gap']:+.1f}% |")
        lines.append("")

    lines.append("> ⚠️ 触发≠立即买。左侧分层：目标价打9折、仓位减半、观察1周。")

    push(f"📊 触发价总监控（{len(hit)}触发/{len(buy)}可买）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
