"""
财报扫描器 v2
修复：set→list + API参数调试
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
    """东财 datacenter → 逐季度取财报"""
    results = {}
    for date in ["2026-03-31", "2025-12-31"]:
        code_filter = ",".join(f'"{c}"' for c in codes)
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get"
            "?reportName=RPT_DMSK_FN_MAININDICATOR"
            "&columns=SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,"
            "TOTAL_OPERATE_INCOME_YOY,PARENT_NETPROFIT_YOY,"
            "WEIGHTAVG_ROE,GROSS_PROFIT_RATIO"
            f"&filter=(SECURITY_CODE+in+({code_filter}))(REPORT_DATE='{date}')"
            "&pageNumber=1&pageSize=100&sortTypes=-1&sortColumns=REPORT_DATE"
        )
        try:
            r = requests.get(url, timeout=15,
                headers={"Referer": "https://data.eastmoney.com/"})
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


def judge_deterioration(fin_data):
    """评分恶化"""
    latest = list(fin_data.values())[0] if fin_data else {}
    prev = list(fin_data.values())[1] if len(fin_data) > 1 else None
    rev, profit, roe, margin = latest.get("rev_yoy"), latest.get("profit_yoy"), latest.get("roe"), latest.get("margin")
    issues, score = [], 0
    if rev is not None and rev < -10:
        issues.append(f"营收{rev:+.1f}%"); score += 1
    if profit is not None and profit < -20:
        issues.append(f"利润{profit:+.1f}%"); score += 2
    if roe is not None and roe < 5:
        issues.append(f"ROE{roe:.1f}%"); score += 1
    if margin is not None and margin < 15:
        issues.append(f"毛利率{margin:.1f}%"); score += 1
    if prev:
        pp, pr = prev.get("profit_yoy"), prev.get("rev_yoy")
        if pp is not None and profit is not None and profit < pp - 10:
            issues.append("利润加速下滑"); score += 1
        if pr is not None and rev is not None and rev < pr - 5:
            issues.append("营收加速下滑"); score += 1
    if score >= 4: return "🔴严重恶化", "卖出/不买入", issues
    if score >= 2: return "🟡轻度恶化", "观察等待", issues
    if score >= 1: return "🟢微瑕", "密切跟踪", issues
    return "✅健康", "触发即买入", []


def batch_prices(codes):
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if m:
                    parts = m.group().split("~")
                    if len(parts) >= 4 and parts[3]:
                        prices[c] = float(parts[3])
        except:
            pass
    return prices


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title, "content": content,
            "template": "markdown",
            "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 财报扫描器 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}

    # set→list 存
    prev_triggered = set(state.get("prev_triggered", []))
    new_triggers = triggered - prev_triggered

    codes = sorted(held | triggered)
    print(f"  持仓{len(held)}+触发{len(triggered)}(新{len(new_triggers)})={len(codes)}只")

    fin_data = fetch_financials(codes)
    prices = batch_prices(codes)
    print(f"  财报{len(fin_data)}只 现价{len(prices)}只")

    alerts, healthy, new_scan = [], [], []

    for code in codes:
        n = hold[code].get("name", code) if code in hold and isinstance(hold.get(code), dict) else trigger.get(code, {}).get("name", code) if isinstance(trigger.get(code), dict) else code
        tag = "持仓" if code in held else "触发"
        a = ATTR.get(code, "?")
        fd = fin_data.get(code, {})
        if not fd: continue
        rating, sug, issues = judge_deterioration(fd)
        row = {"name": n, "tag": tag, "attr": a, "rating": rating, "sug": sug, "issues": issues, "price": prices.get(code, 0), "tp": trigger.get(code, {}).get("trigger_price", 0) if isinstance(trigger.get(code), dict) else 0, "fin": fd}
        if "恶化" in rating: alerts.append(row)
        else: healthy.append(row)
        if code in new_triggers: new_scan.append(row)

    lines = [f"财报扫描器 {now:%m}.{now:%d}", f"最新季报 | {len(codes)}只 | 有财报{len(fin_data)}只"]

    if alerts:
        lines.append(""); lines.append("⚠️ 恶化告警")
        for r in alerts:
            lat = list(r["fin"].values())[0]
            lines.append(f"  - {r['rating']} {r['name']}[{r['tag']}] {r['attr']}")
            lines.append(f"    营收{lat.get('rev_yoy','?'):.1f}% 利润{lat.get('profit_yoy','?'):.1f}% ROE{lat.get('roe','?'):.1f}%")
            lines.append(f"    → {r['sug']}")

    if healthy:
        lines.append(""); lines.append(f"健康 {len(healthy)}只")
        for r in healthy[:8]:
            lat = list(r["fin"].values())[0]
            lines.append(f"  - {r['name']}[{r['tag']}] {r['attr']} | 营收{lat.get('rev_yoy','?'):.1f}% ROE{lat.get('roe','?'):.1f}%")

    if new_scan:
        lines.append(""); lines.append(f"🆕 新触发 {len(new_triggers)}只")
        for r in new_scan:
            lines.append(f"  - {r['name']} 现{r['price']:.2f} 触发{r['tp']:.2f}")
            lines.append(f"    财报: {r['rating']} → {r['sug']}")
            if r["issues"]: lines.append(f"    问题: {', '.join(r['issues'])}")

    if not alerts and not new_scan:
        lines.append(""); lines.append("无恶化/无新触发")

    lines.append(""); lines.append(f"> 东财 datacenter 最新季报")

    # 保存（set→list）
    state["prev_triggered"] = list(triggered)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    push(f"财报扫描器 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 恶化{len(alerts)} 健康{len(healthy)} 新触发{len(new_triggers)}")


if __name__ == "__main__":
    main()
