"""
周一汇总 v1
一条推送聚合所有信号
"""
import os
import json
import requests
import re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
SNAP_FILE = Path(__file__).parent / "performance_snapshots.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

DIV_FALLBACK = {
    "002027": 0.33, "600690": 0.38, "000708": 0.55,
    "600845": 0.50, "000157": 0.16, "002601": 0.40,
    "600161": 0.05, "300498": 0.20,
}

GROWTH = {
    "600036": 1.2, "601601": 64.9, "600031": 27.4,
    "600585": -26.0, "600188": 8.5, "600660": 25.0,
    "600941": 5.2, "000333": 14.3, "688187": 24.8,
    "603288": -18.0, "600900": 7.3, "000651": 10.2,
    "600845": -3.5, "002027": 18.0, "000708": 8.2,
    "002601": 45.0, "600161": 46.5, "300498": 110.0,
    "600690": 12.8, "000157": 41.5, "002747": -20.0,
}


def batch_tencent(codes):
    results = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i + 30]
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
                    chg = float(parts[32]) if parts[32] else None
                    if price:
                        results[c] = {"price": price, "pe": pe, "chg": chg}
                except Exception:
                    pass
        except Exception:
            pass
    return results


def get_csi300():
    try:
        r = requests.get("http://qt.gtimg.cn/q=sh000300", timeout=10)
        r.encoding = "gbk"
        m = re.search(r'v_sh000300="[^"]*"', r.text)
        if m:
            parts = m.group().split("~")
            return float(parts[3]) if parts[3] else None
    except Exception:
        pass
    return None


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
    today = now.strftime("%Y-%m-%d")
    print(f"[START] 周一汇总 v1 {today}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    cash = hold.get("cash", 0)

    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    trigger_codes = [c for c in trigger if isinstance(trigger.get(c), dict)]

    quotes = batch_tencent(list(set(hold_codes + trigger_codes)))
    csi300 = get_csi300()

    # ── 1. 总览 ──
    total_mv = cash
    for code in hold_codes:
        q = quotes.get(code, {})
        p = q.get("price", hold[code].get("cost", 0))
        total_mv += p * hold[code].get("shares", 0)

    pos_pct = (total_mv - cash) / total_mv * 100 if total_mv > 0 else 0

    # 周收益
    week_chg_str = ""
    if SNAP_FILE.exists():
        with open(SNAP_FILE, "r") as f:
            snaps = json.load(f)
        dates = sorted(snaps.keys())
        if len(dates) >= 2:
            prev = snaps[dates[-2]]["total_mv"]
            wc = (total_mv - prev) / prev * 100 if prev > 0 else 0
            week_chg_str = f"本周 {wc:+.2f}%"

    lines = [
        f"📊 周一汇总 {now:%m}.{now:%d}",
        f"总{total_mv/10000:.1f}万 | 现金{cash/10000:.1f}万 | 仓位{pos_pct:.0f}% {week_chg_str}",
    ]

    # ── 2. 持仓评分速览 ──
    held_scores = []
    for code in hold_codes:
        v = hold[code]
        q = quotes.get(code, {})
        price = q.get("price", v.get("cost", 0))
        pe = q.get("pe")
        tp = 0
        if isinstance(trigger.get(code), dict):
            tp = trigger[code].get("trigger_price", 0)
        dist = (price - tp) / tp * 100 if tp > 0 else None

        s = 5.0
        if pe is not None:
            if pe < 8:   s += 2
            elif pe < 15: s += 1
            elif pe > 50: s -= 2
            elif pe > 30: s -= 1
        g = GROWTH.get(code)
        if g is not None:
            if g > 20:     s += 1.5
            elif g > 10:   s += 0.5
            elif g < -20:  s -= 2
            elif g < -10:  s -= 1
        if dist is not None and dist < 5:
            s += 1
        div_y = None
        if DIV_FALLBACK.get(code, 0) > 0 and price > 0:
            div_y = DIV_FALLBACK[code] / price * 100
            if div_y > 4: s += 1
            elif div_y > 2: s += 0.5
        s = round(max(0, min(10, s)), 1)

        emoji = "🟢" if s >= 6 else ("🟡" if s >= 4 else "🔴")
        mv = price * v.get("shares", 0)
        wt = mv / total_mv * 100 if total_mv > 0 else 0
        held_scores.append({
            "name": v.get("name", code),
            "score": s, "emoji": emoji, "wt": wt,
            "pe": pe, "dist": dist, "div_y": div_y,
        })

    held_scores.sort(key=lambda x: x["score"], reverse=True)

    score_summary = " ".join(
        f"{h['emoji']}{h['name'][:2]}{h['score']}"
        for h in held_scores
    )
    lines.append("")
    lines.append(f"持仓 {score_summary}")

    # ── 3. 击球区 ──
    close_not_held = []
    for code in trigger_codes:
        if code in hold_codes:
            continue
        t = trigger[code]
        tp = t.get("trigger_price", 0)
        if tp <= 0:
            continue
        q = quotes.get(code, {})
        price = q.get("price", 0)
        if price <= 0:
            continue
        dist = (price - tp) / tp * 100
        if dist <= 10:
            pe = q.get("pe")
            g = GROWTH.get(code)
            close_not_held.append({
                "name": t.get("name", code),
                "price": price, "tp": tp, "dist": dist,
                "pe": pe, "profit": g,
            })

    if close_not_held:
        close_not_held.sort(key=lambda x: x["dist"])
        lines.append("")
        lines.append(f"🎯 击球区（{len(close_not_held)}只）")
        for r in close_not_held[:5]:
            pe_s = f"PE{r['pe']:.0f}" if r["pe"] else ""
            pf_s = f"利{r['profit']:+.0f}%" if r["profit"] is not None else ""
            lines.append(f"- {r['name']} {r['price']:.2f} 距{r['dist']:+.0f}% {pe_s} {pf_s}")

        bullets = max(1, int(cash / 50000))
        per_bullet = int(cash / bullets * 0.3 / 10000)
        lines.append(f"→ 现金{cash/10000:.0f}万={bullets}发 × {per_bullet}万")

    # ── 4. 需要关注 ──
    alerts = []
    # PE > 50
    for code in hold_codes:
        q = quotes.get(code, {})
        pe = q.get("pe")
        if pe and pe > 50:
            alerts.append(f"🔴 {hold[code].get('name', code)} PE{pe:.0f} 高估")

    # 利润 < -20%
    for code in hold_codes:
        g = GROWTH.get(code)
        if g and g < -20:
            alerts.append(f"📉 {hold[code].get('name', code)} 利润{g:+.0f}%")

    # 跌破触发价
    for code in hold_codes:
        t = trigger.get(code, {})
        tp = t.get("trigger_price", 0) if isinstance(t, dict) else 0
        if tp > 0:
            q = quotes.get(code, {})
            price = q.get("price", 0)
            if price and price < tp * 0.95:
                alerts.append(f"⚠️ {hold[code].get('name', code)} 跌破触发{tp:.2f}")

    if alerts:
        lines.append("")
        lines.append("◆ 警报")
        for a in alerts:
            lines.append(f"  {a}")

    # ── 5. 大盘温度 ──
    if csi300:
        lines.append("")
        lines.append(f"沪深300 {csi300:.0f}")

    # ── 6. 下周关注 ──
    lines.append("")
    lines.append(f"> 下周: 季报/分红/异动 → 每日 | 九宫格/共振 → 周一")

    push(f"周一汇总 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
