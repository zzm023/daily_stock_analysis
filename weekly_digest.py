"""
周度估值摘要 v3 - Tushare+腾讯
"""
import os, json, requests, re, time
from datetime import datetime, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

DIV_FB = {
    "600036": 1.97, "601601": 1.02, "600031": 0.39,
    "600585": 1.48, "600188": 1.49, "600660": 1.30,
    "600941": 4.80, "000333": 3.00, "688187": 1.55,
    "603288": 0.75, "600900": 0.82, "000651": 2.38,
    "002601": 0.40, "600161": 0.05, "300498": 0.20,
    "600690": 0.38, "000157": 0.16, "002747": 0.00,
}


def batch_tencent(codes):
    results = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i + 30]
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
                    pb = float(parts[46]) if parts[46] and parts[46] != "-" else None
                    if price: results[c] = {"price": price, "pe": pe, "pb": pb}
                except: pass
        except: pass
    return results


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title, "content": content,
            "template": "markdown", "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
    except: pass


def main():
    now = datetime.now()
    mon = now - timedelta(days=now.weekday())
    week_id = f"{mon.month}/{mon.day}"

    print(f"[START] 周报 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})
    all_codes = list(set(
        [c for c in trigger if isinstance(trigger.get(c), dict)] +
        [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    ))

    quotes = batch_tencent(all_codes)

    # ── Tushare 利润 & 分红 ──
    growth = {}
    divs = {}
    try:
        from tushare_data import get_profit_growth, get_dividends, auto_whitelist
        auto_whitelist()
        growth = get_profit_growth(all_codes)
        divs = get_dividends(all_codes)
        print(f"  Tushare 利润{len(growth)}只 分红{len(divs)}只")
    except Exception as e:
        print(f"  Tushare失败: {e}")

    cash = hold.get("cash", 0)
    total_mv = cash
    hold_rows = []

    for code in hold:
        if code == "cash" or not isinstance(hold.get(code), dict):
            continue
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)
        q = quotes.get(code, {})
        price = q.get("price") or v.get("cost", 0)
        mv = price * shares
        total_mv += mv
        hold_rows.append({"code": code, "name": name, "price": price, "mv": mv})

    hold_rows.sort(key=lambda x: x["mv"], reverse=True)
    lines = [f"周报 {week_id}", f"总市值 {total_mv/10000:.1f}万 | 现金 {cash/10000:.1f}万"]

    lines.append("")
    lines.append("### 持仓")
    for r in hold_rows:
        pct = r["mv"] / total_mv * 100 if total_mv > 0 else 0
        lines.append(f"- {r['name']} {r['price']:.2f} | {r['mv']/10000:.1f}万 ({pct:.0f}%)")

    # 触发区靠近
    lines.append("")
    lines.append("### 触发区靠近")
    near = []
    for code in trigger:
        t = trigger.get(code)
        if not isinstance(t, dict): continue
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        q = quotes.get(code, {})
        price = q.get("price")
        if not price or tp <= 0: continue
        dist = (price - tp) / tp * 100
        if dist <= 15:
            dps = divs.get(code) or DIV_FB.get(code, 0)
            div_yield = dps / price * 100 if dps > 0 else 0
            near.append((name, price, dist, div_yield))

    near.sort(key=lambda x: x[2])
    for name, price, dist, dy in near[:10]:
        lines.append(f"- {name} {price:.2f} 距触发{dist:.0f}% 息{dy:.1f}%")
    if len(near) > 10:
        lines.append(f"- ...等{len(near)-10}只")
    if not near:
        lines.append("- 无靠近触发区个股")

    # 利润信号
    if growth:
        lines.append("")
        lines.append("### 利润正增长")
        pos = [(code, growth[code]) for code in growth if growth[code] > 0]
        pos.sort(key=lambda x: x[1], reverse=True)
        for code, g in pos[:8]:
            name = trigger.get(code, {}).get("name", code)
            lines.append(f"- {name} +{g:.0f}%")
        if len(pos) > 8:
            lines.append(f"- ...等{len(pos)-8}只")

    lines.append("")
    lines.append("> Tushare+腾讯")

    push(f"周报 {week_id}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
