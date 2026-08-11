"""
持仓九宫格体检 v1
一屏：PE / 利润增速 / 距触发价% / 分红 / 仓位% / 健康评分
数据源：腾讯 PE/PB + 东财增速 + 手工分红 + 触发价
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

# 分红兜底
DIV_FALLBACK = {
    "002027": 0.33, "600690": 0.38, "000708": 0.55,
    "600845": 0.50, "000157": 0.16, "002601": 0.40,
    "600161": 0.05, "300498": 0.20, "002747": 0.00,
}


def batch_tencent(codes):
    """腾讯批量 → {code: {price, pe, pb}}"""
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
    """东财 → {rev_yoy, profit_yoy}"""
    prefix = "1" if code.startswith("6") else "0"
    for _ in range(2):
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={"secid": f"{prefix}.{code}", "fields": "f43,f173,f185"},
                timeout=10,
                headers={"Referer": "https://quote.eastmoney.com/"}
            )
            d = r.json().get("data")
            if d and d.get("f43"):
                return {
                    "rev_yoy": d.get("f173"),
                    "profit_yoy": d.get("f185"),
                }
        except Exception:
            pass
        time.sleep(0.5)
    return None


def health_score(pe, profit_yoy, dist_pct, div_yield):
    """综合评分 0-10"""
    score = 5  # 基准

    # PE：越低越好
    if pe is not None:
        if pe < 8:
            score += 2
        elif pe < 15:
            score += 1
        elif pe > 50:
            score -= 2
        elif pe > 30:
            score -= 1

    # 利润增速
    if profit_yoy is not None:
        if profit_yoy > 20:
            score += 1.5
        elif profit_yoy > 10:
            score += 0.5
        elif profit_yoy < -20:
            score -= 2
        elif profit_yoy < -10:
            score -= 1

    # 距触发价
    if dist_pct is not None:
        if dist_pct < 5:
            score += 1
        elif dist_pct > 30:
            score -= 1

    # 股息率
    if div_yield is not None:
        if div_yield > 4:
            score += 1
        elif div_yield > 2:
            score += 0.5

    return max(0, min(10, round(score, 1)))


def grade(score):
    if score >= 8:
        return "🟢优秀"
    if score >= 6:
        return "🟡良好"
    if score >= 4:
        return "🟠观望"
    return "🔴警惕"


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
    print(f"[START] 持仓九宫格 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    cash = hold.get("cash", 0)

    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    # 取行情
    quotes = batch_tencent(hold_codes)
    print(f"  行情 {len(quotes)} 只")

    # 算总市值
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

        # 触发价
        tp = trigger.get(code, {}).get("trigger_price", 0) if isinstance(trigger.get(code), dict) else 0

        # 距触发价 %
        dist_pct = ((price - tp) / tp * 100) if tp > 0 else None

        # 分红
        dps = DIV_FALLBACK.get(code, 0)
        div_total = shares * dps
        div_yield = (dps / price * 100) if price > 0 and dps > 0 else None

        # 增速
        growth = get_growth(code)
        rev = growth.get("rev_yoy") if growth else None
        profit = growth.get("profit_yoy") if growth else None

        # 评分
        score = health_score(pe, profit, dist_pct, div_yield)

        rows.append({
            "name": name, "code": code,
            "price": price, "pe": pe, "pb": pb,
            "shares": shares, "mv": mv,
            "tp": tp, "dist_pct": dist_pct,
            "dps": dps, "div_total": div_total, "div_yield": div_yield,
            "rev": rev, "profit": profit,
            "score": score,
        })

        print(f"  {name} PE{pe} 利润{profit}% 距触发{dist_pct}% → {score}分")

    # 仓位占比
    for r in rows:
        r["weight"] = (r["mv"] / total_mv * 100) if total_mv > 0 else 0

    # 按评分排序
    rows.sort(key=lambda x: x["score"], reverse=True)

    lines = [
        f"持仓九宫格 {now:%m}.{now:%d}",
        f"总资产{total_mv/10000:.1f}万 | 现金{cash/10000:.1f}万",
        "",
        "| 股票 | 评分 | PE | 利润增速 | 距触发 | 股息率 | 仓位 |",
        "|:--|:--:|:--:|:--:|:--:|:--:|:--:|",
    ]

    for r in rows:
        pe_str = f"{r['pe']:.1f}" if r["pe"] else "?"
        profit_str = f"{r['profit']:+.1f}%" if r["profit"] is not None else "?"
        dist_str = f"{r['dist_pct']:+.1f}%" if r["dist_pct"] is not None else "?"
        div_str = f"{r['div_yield']:.1f}%" if r["div_yield"] else "-"
        weight_str = f"{r['weight']:.1f}%"

        lines.append(
            f"| {r['name']} | {grade(r['score'])} {r['score']} | "
            f"{pe_str} | {profit_str} | {dist_str} | {div_str} | {weight_str} |"
        )

    lines.append("")

    # 分红合计
    total_div = sum(r["div_total"] for r in rows)
    lines.append(f"全年分红: {total_div/10000:.2f}万 | 已收: 估算中")

    # 高仓位提醒
    heavy = [r for r in rows if r["weight"] > 15]
    if heavy:
        lines.append("⚠️ 仓位>15%: " + ", ".join(r["name"] for r in heavy))

    # 需加仓
    buy_zone = [r for r in rows if r["dist_pct"] is not None and r["dist_pct"] < 5 and r["score"] >= 5]
    if buy_zone:
        lines.append("🎯 加仓区: " + ", ".join(r["name"] for r in buy_zone))

    # 需关注
    watch = [r for r in rows if r["score"] < 5]
    if watch:
        lines.append("🔍 关注: " + ", ".join(r["name"] for r in watch))

    lines.append("")
    lines.append("> 评分=PE+增速+距触发+股息 | 每周一更新")

    push(f"持仓体检 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
