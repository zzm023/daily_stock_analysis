"""
持仓九宫格 v5 - Tushare数据层
"""
import os, json, requests, re, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 本地兜底（Tushare 挂的时候用）
GROWTH_FB = {
    "600036": 1.2, "601601": 64.9, "600031": 27.4,
    "600585": -26.0, "600188": 8.5, "600660": 25.0,
    "600941": 5.2, "000333": 14.3, "688187": 24.8,
    "603288": -18.0, "600900": 7.3, "000651": 10.2,
    "002601": 45.0, "600161": 46.5, "300498": 110.0,
    "600690": 12.8, "000157": 41.5, "002747": -20.0,
}
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
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 48:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    pb = float(parts[46]) if parts[46] and parts[46] != "-" else None
                    if price:
                        results[c] = {"price": price, "pe": pe, "pb": pb}
                except:
                    pass
        except:
            pass
    return results


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title, "content": content,
            "template": "markdown", "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 九宫格 v5 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    cash = hold.get("cash", 0)
    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]

    quotes = batch_tencent(hold_codes)

    # ── Tushare 利润 & 分红 ──
    growth = {}
    divs = {}
    try:
        from tushare_data import get_profit_growth, get_dividends, auto_whitelist
        auto_whitelist()
        growth = get_profit_growth(hold_codes)
        divs = get_dividends(hold_codes)
        print(f"  Tushare 利润{len(growth)}只 分红{len(divs)}只")
    except Exception as e:
        print(f"  Tushare 失败: {e}，用兜底")

    total_mv = cash
    rows = []

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)
        cost = v.get("cost", 0)

        q = quotes.get(code, {})
        price = q.get("price", cost)
        pe = q.get("pe")
        pb = q.get("pb")
        mv = price * shares
        total_mv += mv

        tp = 0
        if isinstance(trigger.get(code), dict):
            tp = trigger[code].get("trigger_price", 0)
        dist_pct = ((price - tp) / tp * 100) if tp > 0 else None

        # 分红: Tushare优先 → 兜底 → 0
        dps = divs.get(code) or DIV_FB.get(code, 0)
        div_total = shares * dps
        div_yield = (dps / price * 100) if price > 0 and dps > 0 else None

        # 利润: Tushare优先 → 兜底
        profit = growth.get(code) or GROWTH_FB.get(code)

        s = 5.0
        if pe is not None:
            if pe < 8: s += 2
            elif pe < 15: s += 1
            elif pe > 50: s -= 2
            elif pe > 30: s -= 1
        if profit is not None:
            if profit > 20: s += 1.5
            elif profit > 10: s += 0.5
            elif profit < -20: s -= 2
            elif profit < -10: s -= 1
        if dist_pct is not None:
            if dist_pct < 5: s += 1
            elif dist_pct > 30: s -= 1
        if div_yield is not None:
            if div_yield > 4: s += 1
            elif div_yield > 2: s += 0.5
        s = round(max(0, min(10, s)), 1)

        rows.append({
            "name": name, "price": price, "pe": pe, "pb": pb,
            "mv": mv, "tp": tp, "dist_pct": dist_pct,
            "div_yield": div_yield, "div_total": div_total,
            "profit": profit, "score": s,
        })

    for r in rows:
        r["weight"] = (r["mv"] / total_mv * 100) if total_mv > 0 else 0
    rows.sort(key=lambda x: x["score"], reverse=True)

    def fmt(r):
        p = []
        p.append(f"PE{r['pe']:.0f}" if r["pe"] else "PE?")
        if r["profit"] is not None: p.append(f"利{r['profit']:+.0f}%")
        if r["dist_pct"] is not None: p.append(f"距{r['dist_pct']:+.0f}%")
        if r["div_yield"]: p.append(f"息{r['div_yield']:.1f}%")
        p.append(f"仓{r['weight']:.0f}%")
        return "  ".join(p)

    good = [r for r in rows if r["score"] >= 6]
    warn = [r for r in rows if 4 <= r["score"] < 6]
    bad = [r for r in rows if r["score"] < 4]

    lines = [
        f"持仓体检 {now:%m}.{now:%d}",
        f"总{total_mv/10000:.1f}万 | 现金{cash/10000:.1f}万 | 仓位{(total_mv-cash)/total_mv*100:.0f}%",
    ]
    if good:
        lines.append(""); lines.append("◆ 健康")
        for r in good:
            lines.append(f"🟢 {r['name']} {r['score']}")
            lines.append(f"   {fmt(r)}")
    if warn:
        lines.append(""); lines.append("◆ 注意")
        for r in warn:
            lines.append(f"🟡 {r['name']} {r['score']}")
            lines.append(f"   {fmt(r)}")
    if bad:
        lines.append(""); lines.append("◆ 危险")
        for r in bad:
            lines.append(f"🔴 {r['name']} {r['score']}")
            lines.append(f"   {fmt(r)}")

    total_div = sum(r["div_total"] for r in rows)
    lines.append(""); lines.append(f"💵 全年分红 {total_div/10000:.2f}万")

    buy_zone = [r for r in rows if r["dist_pct"] is not None and r["dist_pct"] < 5 and r["score"] >= 5]
    if buy_zone:
        lines.append(f"🎯 加仓区 {' '.join(r['name'] for r in buy_zone)}")

    lines.append("")
    lines.append("> PE 利=利润增速 距=距触发价 息=股息率 | Tushare+腾讯")

    push(f"持仓体检 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
