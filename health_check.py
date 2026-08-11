"""
持仓九宫格 v2
紧凑文本 + 放宽超时 + 东财重试
"""
import os
import json
import requests
import re
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

DIV_FALLBACK = {
    "002027": 0.33, "600690": 0.38, "000708": 0.55,
    "600845": 0.50, "000157": 0.16, "002601": 0.40,
    "600161": 0.05, "300498": 0.20, "002747": 0.00,
}


def batch_tencent(codes):
    results = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i+30]
        symbols = ",".join(
            f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch
        )
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
                except Exception:
                    pass
        except Exception:
            pass
    return results


def get_growth(code):
    prefix = "1" if code.startswith("6") else "0"
    for attempt in range(3):
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={
                    "secid": f"{prefix}.{code}",
                    "fields": "f43,f173,f185",
                },
                timeout=15,
                headers={
                    "Referer": "https://quote.eastmoney.com/",
                    "User-Agent": "Mozilla/5.0",
                }
            )
            d = r.json().get("data")
            if d and d.get("f43"):
                return {
                    "rev_yoy": d.get("f173"),
                    "profit_yoy": d.get("f185"),
                }
        except Exception:
            pass
        time.sleep(1.0 if attempt == 0 else 2.0)
    return None


def score_emoji(s):
    if s >= 8:
        return "🟢"
    if s >= 6:
        return "🟡"
    if s >= 4:
        return "🟠"
    return "🔴"


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
    print(f"[START] 持仓九宫格 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    cash = hold.get("cash", 0)

    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    quotes = batch_tencent(hold_codes)
    print(f"  行情 {len(quotes)} 只")

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

        dps = DIV_FALLBACK.get(code, 0)
        div_total = shares * dps
        div_yield = (dps / price * 100) if price > 0 and dps > 0 else None

        growth = get_growth(code)
        rev = growth.get("rev_yoy") if growth else None
        profit = growth.get("profit_yoy") if growth else None

        # 评分
        s = 5.0
        if pe is not None:
            if pe < 8:   s += 2
            elif pe < 15: s += 1
            elif pe > 50: s -= 2
            elif pe > 30: s -= 1
        if profit is not None:
            if profit > 20:     s += 1.5
            elif profit > 10:   s += 0.5
            elif profit < -20:  s -= 2
            elif profit < -10:  s -= 1
        if dist_pct is not None:
            if dist_pct < 5:    s += 1
            elif dist_pct > 30: s -= 1
        if div_yield is not None:
            if div_yield > 4:   s += 1
            elif div_yield > 2: s += 0.5
        s = round(max(0, min(10, s)), 1)

        rows.append({
            "name": name, "price": price, "pe": pe, "pb": pb,
            "mv": mv, "tp": tp, "dist_pct": dist_pct,
            "div_yield": div_yield, "div_total": div_total,
            "rev": rev, "profit": profit, "score": s,
        })
        print(f"  {name} PE{pe} 利润{profit}% dist{dist_pct} → {s}")

    for r in rows:
        r["weight"] = (r["mv"] / total_mv * 100) if total_mv > 0 else 0
    rows.sort(key=lambda x: x["score"], reverse=True)

    # 紧凑文本
    lines = [
        f"持仓九宫格 {now:%m}.{now:%d}",
        f"总{total_mv/10000:.1f}万 | 现金{cash/10000:.1f}万 | 仓位{(total_mv-cash)/total_mv*100:.0f}%",
    ]

    for r in rows:
        pe_s = f"PE{r['pe']:.0f}" if r["pe"] else "PE?"
        pf_s = f"利{r['profit']:+.0f}%" if r["profit"] is not None else "利?"
        ds_s = f"距{r['dist_pct']:+.0f}%" if r["dist_pct"] is not None else ""
        dv_s = f"息{r['div_yield']:.1f}%" if r["div_yield"] else ""
        wt_s = f"{r['weight']:.0f}%"

        line = (f"{score_emoji(r['score'])} {r['name']} "
                f"{pe_s} {pf_s} {ds_s} {dv_s} 仓{wt_s} 评分{r['score']}")
        lines.append(line)

    # 分红合计
    total_div = sum(r["div_total"] for r in rows)
    lines.append("")
    lines.append(f"全年分红 {total_div/10000:.2f}万 | 已收约{total_div/10000:.2f}万")

    # 提醒
    heavy = [r for r in rows if r["weight"] > 15]
    buy_zone = [r for r in rows if r["dist_pct"] is not None and r["dist_pct"] < 5 and r["score"] >= 5]
    watch = [r for r in rows if r["score"] < 5]

    if heavy:
        lines.append(f"⚠️ 仓位>15%: {' '.join(r['name'] for r in heavy)}")
    if buy_zone:
        lines.append(f"🎯 加仓区: {' '.join(r['name'] for r in buy_zone)}")
    if watch:
        lines.append(f"🔍 关注: {' '.join(r['name'] for r in watch)}")

    lines.append("")
    lines.append("> PE+增速+距触发+股息 → 综合评分 | 每周一")

    push(f"持仓体检 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
