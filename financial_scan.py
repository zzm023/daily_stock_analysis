"""
财报扫描器 v4
东财 push2 → f173=营收增速 f184=PE f185=利润增速 f46=PB
"""
import os, json, requests, re, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

ATTR = {
    "600036":"①永续债","601601":"①永续债","600018":"①永续债",
    "601816":"①永续债","600900":"①永续债","600941":"①永续债",
    "000429":"①永续债","600007":"①永续债",
    "600188":"②高息成长","600585":"②高息成长","300498":"②高息成长",
    "603568":"②高息成长","600598":"②高息成长",
    "000792":"③周期拐点","600299":"③周期拐点","002601":"③周期拐点",
    "603806":"③周期拐点",
    "600309":"④全球寡头","600660":"④全球寡头","601058":"④全球寡头",
    "600406":"④全球寡头","000651":"④全球寡头","000333":"④全球寡头",
    "300124":"④全球寡头",
    "000538":"⑤品牌心智","603605":"⑤品牌心智","605098":"⑤品牌心智",
    "600298":"⑤品牌心智","603288":"⑤品牌心智","002027":"⑤品牌心智",
    "600690":"⑤品牌心智",
    "002508":"⑥小众冠军","002032":"⑥小众冠军","002884":"⑥小众冠军",
    "002318":"⑥小众冠军","603855":"⑥小众冠军","603508":"⑥小众冠军",
    "300628":"⑥小众冠军","000708":"⑥小众冠军","000157":"⑥小众冠军",
    "600031":"⑥小众冠军","600761":"⑥小众冠军","600066":"⑥小众冠军",
    "600486":"⑥小众冠军",
    "688187":"科技⚠","300832":"科技⚠","002837":"科技⚠",
    "300627":"科技⚠","002410":"科技⚠","600845":"科技⚠",
    "002747":"科技⚠","600161":"科技⚠",
}


def get_fin(code):
    """东财 push2 → {price, pb, rev_yoy, pe, profit_yoy}"""
    prefix = "1" if code.startswith("6") else "0"
    for attempt in range(2):
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={
                    "secid": f"{prefix}.{code}",
                    "fields": "f43,f46,f57,f58,f173,f184,f185",
                },
                timeout=10,
                headers={"Referer": "https://quote.eastmoney.com/"}
            )
            d = r.json().get("data")
            if d and d.get("f43"):
                return {
                    "price": d["f43"] / 100,
                    "pb": d.get("f46"),        # PB
                    "rev_yoy": d.get("f173"),  # 营收增速 %
                    "pe": d.get("f184"),       # PE
                    "profit_yoy": d.get("f185"), # 利润增速 %
                }
        except:
            pass
        if attempt == 0:
            time.sleep(0.5)
    return None


def judge(name, d, attr_label):
    """恶化评分 → (评级, 建议, 问题列表)"""
    rev, profit, pe, pb = d.get("rev_yoy"), d.get("profit_yoy"), d.get("pe"), d.get("pb")
    issues, score = [], 0

    if profit is not None and profit < -20:
        issues.append(f"利润{profit:+.1f}%")
        score += 2
    elif profit is not None and profit < -10:
        issues.append(f"利润{profit:+.1f}%")
        score += 1

    if rev is not None and rev < -10:
        issues.append(f"营收{rev:+.1f}%")
        score += 1
    elif rev is not None and rev < 0:
        issues.append(f"营收{rev:+.1f}%")
        score += 0.5

    if pe is not None and pe > 80:
        issues.append(f"PE{pe:.0f}")
        score += 1

    if pb is not None and pb < 0.8:
        issues.append(f"破净PB{pb:.2f}")
        score -= 1  # 减分=好

    if score >= 3:
        return "🔴严重恶化", "建议卖出/禁止买入", issues
    elif score >= 2:
        return "🟡轻度恶化", "观察等待，暂不加仓", issues
    elif score >= 1:
        return "🟢微瑕", "可持有，密切跟踪", issues
    elif score < 0:
        return "💎价值低估", "触发即重仓", issues
    else:
        return "✅健康", "触发即买入", issues


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title, "content": content,
            "template": "markdown", "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 财报扫描器 v4 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}
    prev_triggered = set(state.get("prev_triggered", []))
    new_triggers = triggered - prev_triggered

    codes = sorted(held | triggered)
    print(f"  持仓{len(held)}+触发{len(triggered)}(新{len(new_triggers)})={len(codes)}只")

    alerts, healthy, new_scan, no_data = [], [], [], []
    fin_map = {}

    for i, code in enumerate(codes):
        n = hold[code].get("name", code) if code in hold and isinstance(hold.get(code), dict) else trigger.get(code, {}).get("name", code) if isinstance(trigger.get(code), dict) else code
        tag = "持仓" if code in held else "触发"
        a = ATTR.get(code, "?")

        d = get_fin(code)
        if not d:
            no_data.append(f"{n}[{tag}]")
            continue

        fin_map[code] = d
        rating, sug, issues = judge(n, d, a)

        row = {"name": n, "tag": tag, "attr": a, "rating": rating, "sug": sug, "issues": issues, "price": d["price"], "pe": d.get("pe"), "pb": d.get("pb"), "rev": d.get("rev_yoy"), "profit": d.get("profit_yoy")}

        if "恶化" in rating:
            alerts.append(row)
        else:
            healthy.append(row)

        if code in new_triggers:
            new_scan.append(row)

        print(f"  [{i+1}/{len(codes)}] {n} 利润{row['profit']}% PE{row['pe']} → {rating}")

    # 保存
    state["prev_triggered"] = list(triggered)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    lines = [
        f"财报扫描器 {now:%m}.{now:%d}",
        f"最新季报 | {len(codes)-len(no_data)}/{len(codes)}只有数据",
    ]

    if alerts:
        lines.append(""); lines.append("⚠️ 恶化告警")
        for r in alerts:
            lines.append(f"  - {r['rating']} {r['name']}[{r['tag']}] {r['attr']}")
            lines.append(f"    利润{r['profit']:+.1f}% 营收{r['rev']:+.1f}% PE{r['pe']:.1f} PB{r['pb']:.2f}")
            lines.append(f"    → {r['sug']}")
            if r["issues"]: lines.append(f"    问题: {', '.join(r['issues'])}")

    if healthy:
        lines.append(""); lines.append(f"财务健康 {len(healthy)}只")
        for r in healthy:
            lines.append(f"  - {r['rating']} {r['name']}[{r['tag']}] {r['attr']} | 利润{r['profit']:+.1f}% 营收{r['rev']:+.1f}% PE{r['pe']:.1f}")

    if new_scan:
        lines.append(""); lines.append(f"🆕 新触发 ({len(new_triggers)}只)")
        for r in new_scan:
            tp = trigger.get(code, {}).get("trigger_price", 0) if isinstance(trigger.get(code), dict) else 0
            lines.append(f"  - {r['name']} 现{r['price']:.2f} PE{r['pe']:.1f} PB{r['pb']:.2f}")
            lines.append(f"    {r['rating']} → {r['sug']}")

    if no_data:
        lines.append(""); lines.append(f"无数据 {len(no_data)}只")
        lines.append(f"  {', '.join(no_data[:6])}")

    if not alerts and not new_scan:
        lines.append(""); lines.append("无恶化/无新触发")

    lines.append(""); lines.append(f"> 东财 push2 f173=营收 f184=PE f185=利润增速 f46=PB")

    push(f"财报扫描器 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 恶化{len(alerts)} 健康{len(healthy)} 新触发{len(new_triggers)}")


if __name__ == "__main__":
    main()
