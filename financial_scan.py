"""
财报扫描器 v1
东财 datacenter → 最新季度全市场 → 筛持仓+触发 → 判断恶化
新触发股票深度扫描 → 买卖建议
"""
import os, json, requests, re
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


def fetch_financials(codes):
    """东财 datacenter → 最新季度财报 → {code: {指标}}"""
    # 取最近两个报告期：2026-03-31, 2025-12-31
    results = {}
    for date in ["2026-03-31", "2025-12-31"]:
        code_filter = ",".join(f'"{c}"' for c in codes)
        try:
            r = requests.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={
                    "reportName": "RPT_DMSK_FN_MAININDICATOR",
                    "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,"
                               "TOTAL_OPERATE_INCOME_YOY,PARENT_NETPROFIT_YOY,"
                               "WEIGHTAVG_ROE,GROSS_PROFIT_RATIO",
                    "filter": f'(SECURITY_CODE in ({code_filter}))(REPORT_DATE=\'{date}\')',
                    "pageNumber": 1,
                    "pageSize": 100,
                    "sortTypes": -1,
                    "sortColumns": "REPORT_DATE",
                },
                timeout=15,
                headers={"Referer": "https://data.eastmoney.com/"}
            )
            data = r.json()
            if data.get("success") and data.get("result") and data["result"].get("data"):
                for item in data["result"]["data"]:
                    code = item.get("SECURITY_CODE", "")
                    if code not in results:
                        results[code] = {}
                    results[code][item["REPORT_DATE"][:7]] = {
                        "rev_yoy": item.get("TOTAL_OPERATE_INCOME_YOY"),
                        "profit_yoy": item.get("PARENT_NETPROFIT_YOY"),
                        "roe": item.get("WEIGHTAVG_ROE"),
                        "margin": item.get("GROSS_PROFIT_RATIO"),
                    }
        except Exception as e:
            print(f"  财报获取失败 ({date}): {e}")
    return results


def judge_deterioration(name, fin_data, attr_label):
    """判断恶化程度 → (评级, 建议)"""
    latest = list(fin_data.values())[0] if fin_data else {}
    prev = list(fin_data.values())[1] if len(fin_data) > 1 else None

    rev = latest.get("rev_yoy")
    profit = latest.get("profit_yoy")
    roe = latest.get("roe")
    margin = latest.get("margin")

    issues = []
    score = 0  # 越高越差

    if rev is not None and rev < -10:
        issues.append(f"营收{rev:+.1f}%")
        score += 1
    if profit is not None and profit < -20:
        issues.append(f"利润{profit:+.1f}%")
        score += 2
    if roe is not None and roe < 5:
        issues.append(f"ROE{roe:.1f}%")
        score += 1
    if margin is not None and margin < 15:
        issues.append(f"毛利率{margin:.1f}%")
        score += 1

    # 趋势恶化
    if prev:
        prev_profit = prev.get("profit_yoy")
        prev_rev = prev.get("rev_yoy")
        if prev_profit is not None and profit is not None and profit < prev_profit - 10:
            issues.append("利润加速下滑")
            score += 1
        if prev_rev is not None and rev is not None and rev < prev_rev - 5:
            issues.append("营收加速下滑")
            score += 1

    if score >= 4:
        return "🔴 严重恶化", "建议卖出/不买入", issues
    elif score >= 2:
        return "🟡 轻度恶化", "观察等待，暂不加仓", issues
    elif score >= 1:
        return "🟢 微瑕", "可持有，密切关注", issues
    else:
        return "✅ 财务健康", "触发即买入", []


def batch_prices(codes):
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            text = r.text
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", text)
                if m:
                    parts = m.group().split("~")
                    if len(parts) >= 4 and parts[3]:
                        prices[c] = float(parts[3])
        except:
            pass
    return prices


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 财报扫描器 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}

    # 新触发检测（上次不在触发列表中的）
    prev_triggered = state.get("prev_triggered", set())
    new_triggers = triggered - prev_triggered
    state["prev_triggered"] = triggered

    codes = sorted(held | triggered)
    print(f"  持仓{len(held)} + 触发{len(triggered)}（新{len(new_triggers)}）= {len(codes)}只")

    fin_data = fetch_financials(codes)
    prices = batch_prices(codes)
    print(f"  财报{len(fin_data)}只 现价{len(prices)}只")

    lines = [
        f"财报扫描器 {now:%m}.{now:%d}",
        f"最新季报 | 持仓+触发 {len(codes)}只 | 有财报{len(fin_data)}只",
    ]

    alerts = []
    healthy = []
    new_trigger_scan = []

    for code in codes:
        if code in hold and isinstance(hold.get(code), dict):
            name = hold[code].get("name", code)
        else:
            name = trigger.get(code, {}).get("name", code) if isinstance(trigger.get(code), dict) else code
        tag = "持仓" if code in held else "触发"
        a = ATTR.get(code, "?")

        fd = fin_data.get(code, {})
        if not fd:
            continue

        rating, suggestion, issues = judge_deterioration(name, fd, a)
        price = prices.get(code, 0)
        tp = trigger.get(code, {}).get("trigger_price", 0) if isinstance(trigger.get(code), dict) else 0

        row = {
            "name": name, "tag": tag, "attr": a,
            "rating": rating, "suggestion": suggestion,
            "issues": issues, "price": price, "tp": tp,
            "fin": fd,
        }

        if "恶化" in rating:
            alerts.append(row)
        else:
            healthy.append(row)

        # 新触发深度扫描
        if code in new_triggers:
            new_trigger_scan.append(row)

    # 告警
    if alerts:
        lines.append("")
        lines.append("⚠️ 财务恶化告警")
        for r in alerts:
            latest = list(r["fin"].values())[0]
            lines.append(f"  - {r['rating']} {r['name']}[{r['tag']}] {r['attr']}")
            lines.append(f"    营收{latest.get('rev_yoy','?'):.1f}% 利润{latest.get('profit_yoy','?'):.1f}% ROE{latest.get('roe','?'):.1f}%")
            lines.append(f"    → {r['suggestion']}")

    # 健康
    if healthy:
        lines.append("")
        lines.append(f"财务健康 {len(healthy)}只")
        for r in healthy[:8]:
            latest = list(r["fin"].values())[0]
            lines.append(f"  - {r['name']}[{r['tag']}] {r['attr']} | 营收{latest.get('rev_yoy','?'):.1f}% ROE{latest.get('roe','?'):.1f}%")

    # 新触发深度建议
    if new_trigger_scan:
        lines.append("")
        lines.append(f"🆕 新触发股票 ({len(new_triggers)}只)")
        for r in new_trigger_scan:
            latest = list(r["fin"].values())[0]
            lines.append(f"  - {r['name']} 现价{r['price']:.2f} 触发{r['tp']:.2f}")
            lines.append(f"    财报: {r['rating']}")
            lines.append(f"    → {r['suggestion']}")
            if r["issues"]:
                lines.append(f"    问题: {', '.join(r['issues'])}")

    if not alerts and not new_trigger_scan:
        lines.append("")
        lines.append("无恶化告警 | 无新触发")

    lines.append("")
    lines.append(f"> 东财 datacenter 最新季报 | 恶化=营收/利润/ROE/毛利率综合")

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    push(f"财报扫描器 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 恶化{len(alerts)} 健康{len(healthy)} 新触发{len(new_triggers)}")


if __name__ == "__main__":
    main()
