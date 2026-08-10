"""
卖出决策仪表盘 v3
每日联动触发价/估值共振/事件 → 每只持仓独立评分 → LLM分析 → 推送
非卖信号，是综合数据参考
"""
import os
import json
import requests
import subprocess
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 仅在评分达到阈值时调LLM
LLM_THRESHOLD = 4


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


def get_hist_low(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
        r.encoding = "gbk"
        m = r.text.split(",")
        if len(m) > 32 and m[32]:
            return float(m[32])
    except:
        pass
    return 0


def get_hist_high(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
        r.encoding = "gbk"
        m = r.text.split(",")
        if len(m) > 44 and m[44]:
            return float(m[44])
    except:
        pass
    return 0


def call_llm(prompt):
    """调用 DeepSeek 分析"""
    try:
        from llm_utils import call_deepseek
        return call_deepseek(prompt, temperature=0.1, max_tokens=800)
    except:
        return None


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
    print(f"[START] 卖出决策仪表盘 v3 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    events = state.get("events_daily", [])
    earnings = state.get("earnings_events", [])

    rows = []
    high_score_stocks = []

    # ── 获取所有持仓价格（批量） ──
    prices = {}
    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        prices[code] = get_price(code)

    # ── 逐只分析 ──
    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue

        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        note = v.get("note", "")

        # 负成本跳过评分但保留显示
        if cost < 0:
            rows.append({
                "name": name, "code": code, "price": 0, "cost": cost,
                "pnl": "∞", "alerts": "零成本·永久持有", "score": 0,
                "details": []  # special handling
            })
            continue

        price = prices.get(code, 0)
        if price == 0:
            continue

        pnl_pct = (price - cost) / cost * 100
        to_double = (cost * 2 - price) / price * 100

        # ── 联动触发价/估值数据 ──
        t = trigger.get(code, {})
        pe_now = t.get("pe_now") or 0
        pe_upper = t.get("pe_upper") or 0
        pb_now = t.get("pb_now") or 0
        pb_lower = t.get("pb_lower") or 0
        resonance = t.get("resonance", "")
        trigger_price = t.get("trigger_price", 0)
        trigger_status = t.get("status", "")

        # ── 联动历史高低 ──
        low = get_hist_low(code)
        high = get_hist_high(code)
        reb_from_low = round((price - low) / low * 100, 1) if low > 0 else None
        dist_to_high = round((high - price) / high * 100, 1) if high > 0 else None

        # ── 联动事件 ──
        stock_events = [e for e in events if code in str(e)]
        stock_earnings = [e for e in earnings if code in str(e)]

        # ═══════ 评分 ═══════
        score = 0
        alerts = []

        # 翻倍/大涨
        if pnl_pct >= 100:
            score += 4; alerts.append("🔴翻倍")
        elif pnl_pct >= 50:
            score += 2; alerts.append("🟠+50%")

        # PE膨胀
        if pe_now and pe_upper:
            pe_ratio = pe_now / pe_upper
            if pe_ratio >= 2.5:
                score += 3; alerts.append(f"🔴PE{pe_ratio:.1f}x")
            elif pe_ratio >= 1.8:
                score += 1; alerts.append(f"🟠PE{pe_ratio:.1f}x")
        else:
            pe_ratio = None

        # PB膨胀
        if pb_now and pb_lower:
            pb_ratio = pb_now / pb_lower
            if pb_ratio >= 3:
                score += 2; alerts.append(f"🔴PB{pb_ratio:.1f}x")

        # 反弹过激
        if reb_from_low and reb_from_low >= 150:
            score += 3; alerts.append(f"🔴反弹{reb_from_low:.0f}%")
        elif reb_from_low and reb_from_low >= 80:
            score += 1; alerts.append(f"🟠反弹{reb_from_low:.0f}%")

        # 逼近历史新高
        if dist_to_high and dist_to_high <= 5 and high > 0:
            score += 2; alerts.append(f"🔴近新高-{dist_to_high:.0f}%")

        # 基本面事件
        if stock_earnings:
            score += 3; alerts.append("🔴财报恶化")
        elif stock_events:
            score += 1; alerts.append("🟡事件")

        # 收租枯竭（现价股息率 < 1.5%）
        dps = t.get("dps", 0)
        if dps and price:
            cur_yld = dps / price * 100
            cost_yld = dps / cost * 100
            if cur_yld < 1.5:
                score += 2; alerts.append(f"🔴息枯{cur_yld:.1f}%")

        alert_str = " ".join(alerts) if alerts else "—"

        # ── 组装详情 ──
        detail = {
            "name": name, "code": code, "price": price, "cost": cost,
            "pnl": f"{pnl_pct:+.1f}%",
            "to_double": f"{to_double:.0f}%",
            "pe_now": pe_now,
            "pb_now": pb_now,
            "reb_low": f"{reb_from_low:.0f}%" if reb_from_low else "?",
            "dist_high": f"-{dist_to_high:.0f}%" if dist_to_high else "?",
            "resonance": resonance,
            "alerts": alert_str,
            "score": score,
            "cost_yld": f"{dps/cost*100:.1f}%" if dps and cost else "?",
            "cur_yld": f"{dps/price*100:.1f}%" if dps and price else "?"
        }
        rows.append(detail)

        if score >= LLM_THRESHOLD:
            high_score_stocks.append(detail)

        print(f"  {name}: 盈亏{pnl_pct:+.1f}% 翻倍还需{to_double:.0f}% "
              f"PE{pe_now} PB{pb_now} 反弹{reb_from_low}% 评分{score} → {alert_str}")

    # ═══════ 组装推送 ═══════
    rows.sort(key=lambda x: x["score"], reverse=True)

    lines = [f"## 📋 卖出决策仪表盘 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 持仓{len(rows)}只 | 事件{len(events)}条", "",
             "| 股票 | 现价 | 盈亏 | 翻倍还需 | PE | PB | 反弹 | 离新高 | 信号 |",
             "|------|------|------|----------|----|----|------|--------|------|"]

    for r in rows:
        if r.get("pnl") == "∞":
            lines.append(f"| {r['name']} | — | ∞ | — | — | — | — | — | 零成本·永持 |")
            continue
        pe_s = f"{r['pe_now']:.1f}" if r['pe_now'] else "?"
        pb_s = f"{r['pb_now']:.2f}" if r['pb_now'] else "?"
        lines.append(
            f"| {r['name']} | {r['price']:.2f} | {r['pnl']} | {r['to_double']} | "
            f"{pe_s} | {pb_s} | {r['reb_low']} | {r['dist_high']} | {r['alerts']} |"
        )
    lines.append("")

    # ═══════ LLM 深度分析（高分股票） ═══════
    if high_score_stocks:
        lines.append(f"### ⚠️ 卖出信号活跃（{len(high_score_stocks)}只评分≥{LLM_THRESHOLD}）")
        lines.append("")

        for hs in high_score_stocks:
            lines.append(f"**{hs['name']}**（{hs['code']}）")
            lines.append(f"- 成本{hs['cost']:.2f} 现价{hs['price']:.2f} 盈亏{hs['pnl']}")
            lines.append(f"- PE{hs['pe_now']:.1f} PB{hs['pb_now']:.2f} 反弹{hs['reb_low']} 离新高{hs['dist_high']}")
            lines.append(f"- 信号：{hs['alerts']}")
            lines.append("")

        # 调LLM
        llm_prompt = "\n".join([
            f"以下持仓触发卖出信号，请按投资框架分析每只：",
            "",
            *[f"{h['name']}({h['code']}) 成本{h['cost']:.2f} 现价{h['price']:.2f} "
              f"盈亏{h['pnl']} PE{h['pe_now']:.1f} PB{h['pb_now']:.2f} "
              f"信号：{h['alerts']}" for h in high_score_stocks],
            "",
            "框架规则：买垄断等破产价，收租为主。卖出的核心是'生意不再便宜或基本面恶化'。",
            "请逐只分析：是否该考虑卖出？给出理由和风险。不替用户做买卖决定。",
        ])
        llm_result = call_llm("\n".join(llm_prompt))
        if llm_result:
            lines.append("### 🤖 综合卖出分析")
            lines.append("")
            lines.append(llm_result)
            lines.append("")

        lines.append("> 📌 以上为数据参考，最终卖出由你综合判断。")
    else:
        lines.append(f"> ✅ 无卖出信号。所有持仓评分 < {LLM_THRESHOLD}。保持持有。")

    push(f"📋 卖出仪表盘 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(high_score_stocks)}只触发卖出信号")


if __name__ == "__main__":
    main()
