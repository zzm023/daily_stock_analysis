"""
仓位风控 v1
每日检查：单只占比/超标告警/框架外持仓/现金占比
每日 16:30 CST
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

FRAMEWORK_CODES = {
    "600036","601601","600018","601816","600900","600941","600406","600598",
    "603568","600007","000429","000157","600585","000792","600188","002601",
    "600299","300498","000651","600066","000333","600690","600031","600309",
    "600660","600761","600486","601058","603806","000708","002027","000538",
    "603605","605098","600298","300628","002508","002032","002884","002318",
    "603855","603288","603508","600161","300832","688187","300124","002837",
    "300627","002410"
}

POSITION_LIMITS = {
    "①": 15, "②": 8, "③": 3, "④": 2, "⑤": 8, "⑥": 8, "科技": 8,
}


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
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now()
    print(f"[START] 仓位风控 v1 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    total_capital = state.get("meta", {}).get("total_capital", 400000)
    cash = hold.get("cash", 0)

    warnings = []
    positions = []

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue

        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        note = v.get("note", "")

        cost_basis = cost * shares
        pct = cost_basis / total_capital * 100

        # 当前市值
        price = get_price(code)
        market_value = price * shares if price else cost_basis
        market_pct = market_value / (total_capital - cash + sum(
            (get_price(c) or hold[c].get("cost",0)) * hold[c].get("shares",0)
            for c in hold if c != "cash" and isinstance(hold.get(c), dict)
        )) * 100 if price else pct

        in_framework = code in FRAMEWORK_CODES
        t = trigger.get(code, {})
        attr = t.get("attr", "") if in_framework else ""

        # 检查是否超标
        limit = None
        for k, v_lim in POSITION_LIMITS.items():
            if k in attr:
                limit = v_lim
                break
        if not limit:
            limit = 10  # 默认上限

        is_over = pct > limit
        is_outside = not in_framework and "框架外" not in note

        entry = {
            "name": name, "code": code,
            "cost_basis": cost_basis, "cost_pct": pct,
            "price": price, "market_value": market_value,
            "limit": limit, "attr": attr,
            "over": is_over, "outside": is_outside
        }
        positions.append(entry)

        if is_over:
            warnings.append(f"⚠️ **{name}** 成本占比{pct:.1f}% > 上限{limit}%")
        if is_outside:
            warnings.append(f"📌 **{name}** 框架外持仓，注意风险")

    positions.sort(key=lambda x: x["cost_pct"], reverse=True)

    # 现金占比
    stock_value = sum(p["market_value"] for p in positions)
    total_value = stock_value + cash
    cash_pct = cash / total_value * 100 if total_value else 0

    # 组装推送
    lines = [f"## 🛡️ 仓位风控 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 总资产{total_value:,.0f} | 现金{cash:,.0f}({cash_pct:.0f}%)", "",
             "| 股票 | 成本占比 | 市值 | 上限 | 属性 | 状态 |",
             "|------|----------|------|------|------|------|"]

    for p in positions:
        status = "🟢" if not p["over"] and not p["outside"] else "🔴" if p["over"] else "🟡"
        attr_s = p["attr"] if p["attr"] else "框架外"
        lines.append(
            f"| {p['name']} | {p['cost_pct']:.1f}% | {p['market_value']:.0f} | "
            f"{p['limit']}% | {attr_s} | {status} |"
        )
    lines.append(f"| **现金** | {cash_pct:.0f}% | {cash:.0f} | — | — | — |")
    lines.append("")

    if warnings:
        lines.append("### ⚠️ 风控提醒")
        for w in warnings:
            lines.append(w)
        lines.append("")

    push(f"🛡️ 仓位风控 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(warnings)}条警告")


if __name__ == "__main__":
    main()
