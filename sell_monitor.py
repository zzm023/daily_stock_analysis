"""
卖出决策仪表盘 v4
每日联动触发价/估值共振/事件 → 每只持仓独立评分 → 推送
纯文本格式，手机友好，按评分分组，含成本息率/现价息率
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


def get_valuation(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) < 45:
            return 0, 0
        pe = float(parts[39]) if parts[39] and parts[39] != "0.00" else 0
        pb = float(parts[43]) if parts[43] and parts[43] != "0.00" else 0
        return pe, pb
    except:
        return 0, 0


def call_llm(prompt):
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
    print(f"[START] 卖出仪表盘 v4 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})
    events = state.get("events_daily", [])
    earnings = state.get("earnings_events", [])

    high_alert = []
    normal = []
    zero_cost = []

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue

        name = v.get("name", code)
        cost = v.get("cost", 0)

        if cost < 0:
            zero_cost.append(f"**{name}** | 负成本·永久持有")
            continue

        price = get_price(code)
        if price == 0:
            continue

        pnl_pct = (price - cost) / cost * 100
        to_double = (cost * 2 - price) / price * 100

        t = trigger.get(code, {})
        pe_now = t.get("pe_now") or 0
        pb_now = t.get("pb_now") or 0
        if not pe_now or not pb_now:
            _pe, _pb = get_valuation(code)
            if not pe_now: pe_now = _pe
            if not pb_now: pb_now = _pb

        pe_upper = t.get("pe_upper") or 0
        pb_lower = t.get("pb_lower") or 0
        dps = t.get("dps", 0)

        cost_yld = dps / cost * 100 if dps and cost else 0
        cur_yld = dps / price * 100 if dps and price else 0

        # ── 评分 ──
        score = 0
        alerts = []

        if pnl_pct >= 100:
            score += 4; alerts.append("🔴翻倍")
        elif pnl_pct >= 50:
            score += 2; alerts.append("🟠+50%")

        if pe_now and pe_upper:
            pe_ratio = pe_now / pe_upper
            if pe_ratio >= 2.5:
                score += 3; alerts.append(f"PE{pe_ratio:.1f}x")
            elif pe_ratio >= 1.8:
                score += 1; alerts.append(f"PE{pe_ratio:.1f}x")

        if pb_now and pb_lower:
            pb_ratio = pb_now / pb_lower
            if pb_ratio >= 3:
                score += 2; alerts.append(f"PB{pb_ratio:.1f}x")

        stock_earnings = [e for e in earnings if code in str(e)]
        stock_events = [e for e in events if code in str(e)]
        if stock_earnings:
            score += 3; alerts.append("财报恶化")
        elif stock_events:
            score += 1; alerts.append("事件")

        if cur_yld and cur_yld < 1.5:
            score += 2; alerts.append(f"息枯{cur_yld:.1f}%")

        alert_str = " ".join(alerts) if alerts else "—"

        # ── 组装行 ──
        pe_s = f"PE{pe_now:.1f}" if pe_now else "PE?"
        pb_s = f"PB{pb_now:.2f}" if pb_now else "PB?"
        yld_s = f"成本息率{cost_yld:.1f}% 现价息率{cur_yld:.1f}%" if dps else ""
        pe_expand = f"(锚≤{pe_upper}→膨胀{pe_now/pe_upper:.1f}x)" if pe_now and pe_upper else ""
        pb_expand = f"(锚≤{pb_lower}→膨胀{pb_now/pb_lower:.1f}x)" if pb_now and pb_lower else ""

        line = (
            f"**{name}** {price:.2f} | 成本{cost:.2f} | 盈亏{pnl_pct:+.1f}% | 翻倍还需{to_double:.0f}%\n"
            f"> {pe_s}{pe_expand} {pb_s}{pb_expand}\n"
        )
        if yld_s:
            line += f"> {yld_s}\n"
        if alert_str != "—":
            line += f"> → {alert_str}\n"

        entry = {"line": line, "score": score, "alert": alert_str, "name": name,
                 "price": price, "cost": cost, "pnl": f"{pnl_pct:+.1f}%",
                 "pe_now": pe_now, "pb_now": pb_now}

        if score >= LLM_THRESHOLD:
            high_alert.append(entry)
        else:
            normal.append(entry)

        print(f"  {name}: 盈亏{pnl_pct:+.1f}% PE{pe_now:.1f} PB{pb_now:.2f} 评分{score} {alert_str}")

    # ── 组装推送 ──
    lines = [f"## 📋 卖出仪表盘 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 持仓{len(high_alert)+len(normal)+len(zero_cost)}只", ""]

    # 高分预警
    if high_alert:
        high_alert.sort(key=lambda x: x["score"], reverse=True)
        lines.append(f"### ⚠️ 需关注（评分≥{LLM_THRESHOLD}）")
        lines.append("")
        for e in high_alert:
            lines.append(e["line"])

    # 正常持有
    if normal:
        normal.sort(key=lambda x: x["score"], reverse=True)
        lines.append("### 📎 正常持有")
        lines.append("")
        for e in normal:
            lines.append(e["line"])

    # 零成本
    if zero_cost:
        lines.append("### 🏆 零成本·永持")
        lines.append("")
        for z in zero_cost:
            lines.append(z)
            lines.append("")

    # LLM分析
    if high_alert:
        lines.append("---")
        llm_input = "\n".join([
            "以下持仓触发卖出信号，按长线框架分析：",
            "",
            *[f"{e['name']} 成本{e['cost']:.2f} 现价{e['price']:.2f} "
              f"盈亏{e['pnl']} PE{e['pe_now']:.1f} PB{e['pb_now']:.2f} "
              f"→ {e['alert']}" for e in high_alert],
            "",
            "规则：买垄断等破产价。卖出=生意不再便宜或基本面恶化。",
            "逐只分析是否该考虑卖出。不替用户做决定。",
        ])
        llm_result = call_llm(llm_input)
        if llm_result:
            lines.append("")
            lines.append("### 🤖 卖出分析")
            lines.append("")
            lines.append(llm_result)
            lines.append("")
        lines.append("📌 数据参考，最终卖出由你判断。")
    else:
        lines.append("")
        lines.append(f"✅ 所有持仓评分<{LLM_THRESHOLD}，无卖出信号。保持持有。")

    push(f"📋 卖出仪表盘 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(high_alert)}只触发卖出信号")


if __name__ == "__main__":
    main()
