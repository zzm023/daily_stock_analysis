"""
分红金额预测 v1
东财 → 2026年持仓股分红方案 → 每股金额 × 股数 = 到账现金
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_dividends(codes):
    """东财 datacenter → 2026年分红方案"""
    code_filter = ",".join(f'"{c}"' for c in codes)
    try:
        r = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_SHAREBONUS_DETAILLIST",
                "columns": (
                    "SECURITY_CODE,SECURITY_NAME_ABBR,"
                    "CASH_DIVIDEND_RATIO,DIVIDEND_YIELD,"
                    "REGISTRATION_DATE,EX_DIVIDEND_DATE,"
                    "PAYMENT_DATE,PLAN_STATUS"
                ),
                "filter": (
                    f"(SECURITY_CODE in ({code_filter}))"
                    f"(REPORT_YEAR='2026')"
                ),
                "pageNumber": 1,
                "pageSize": 50,
                "sortTypes": -1,
                "sortColumns": "EX_DIVIDEND_DATE",
            },
            timeout=15,
            headers={"Referer": "https://data.eastmoney.com/"}
        )
        data = r.json()
        results = {}
        if data.get("success") and data.get("result"):
            items = data["result"].get("data") or []
            for item in items:
                code = item.get("SECURITY_CODE", "")
                results[code] = {
                    "name": item.get("SECURITY_NAME_ABBR", code),
                    "cash_per10": item.get("CASH_DIVIDEND_RATIO"),
                    "yield_pct": item.get("DIVIDEND_YIELD"),
                    "reg_date": item.get("REGISTRATION_DATE"),
                    "ex_date": item.get("EX_DIVIDEND_DATE"),
                    "pay_date": item.get("PAYMENT_DATE"),
                    "status": item.get("PLAN_STATUS"),
                }
        return results
    except Exception as e:
        print(f"  分红数据获取失败: {e}")
        return {}


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("  PUSHPLUS_TOKEN 未设置，跳过推送")
        return
    try:
        resp = requests.post(
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
        print(f"  推送返回: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"  推送失败: {e}")


def main():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    print(f"[START] 分红金额预测 v1 {today_str}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    print(f"  持仓 {len(hold_codes)} 只，查询分红数据...")
    div_data = get_dividends(hold_codes)
    print(f"  获取 {len(div_data)} 只分红数据")

    rows = []
    total_cash = 0
    no_div = []

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)

        d = div_data.get(code)
        if not d or not d["cash_per10"]:
            no_div.append(name)
            continue

        cash_per10 = d["cash_per10"]
        total = shares * cash_per10 / 10
        total_cash += total

        rows.append({
            "name": name,
            "shares": shares,
            "cash_per10": cash_per10,
            "total": total,
            "ex_date": d.get("ex_date", "?"),
            "pay_date": d.get("pay_date", "?"),
            "status": d.get("status", "?"),
        })

    rows.sort(key=lambda x: (
        x["ex_date"] if x["ex_date"] and x["ex_date"] != "?" else "9999"
    ))

    lines = [
        f"分红金额预测 {now:%m}.{now:%d}",
        f"持仓{len(hold_codes)}只 | 有分红{len(rows)}只 "
        f"| 全年预估{total_cash/10000:.2f}万",
    ]

    # 分组：待收款 vs 已收 vs 未定
    received = []
    pending = []
    upcoming = []
    unknown = []

    for r in rows:
        if r["pay_date"] and r["pay_date"] != "?":
            if r["pay_date"] <= today_str:
                received.append(r)
            elif r["ex_date"] and r["ex_date"] <= today_str:
                pending.append(r)
            else:
                upcoming.append(r)
        else:
            unknown.append(r)

    if received:
        lines.append("")
        lines.append(f"已到账 {len(received)}只")
        for r in received:
            lines.append(
                f"  - {r['name']} {r['cash_per10']:g}/10股 "
                f"x {r['shares']}股 = {r['total']:.0f}元 ✓"
            )

    if pending:
        lines.append("")
        lines.append(f"已除权待收款 {len(pending)}只")
        for r in pending:
            lines.append(
                f"  - {r['name']} {r['total']:.0f}元 → {r['pay_date']}到账"
            )

    if upcoming:
        lines.append("")
        lines.append(f"即将除权 {len(upcoming)}只")
        for r in upcoming:
            lines.append(
                f"  - {r['name']} {r['total']:.0f}元 "
                f"→ 除权{r['ex_date']} 到账{r['pay_date']}"
            )

    if unknown:
        lines.append("")
        lines.append(f"方案待定 {len(unknown)}只")
        for r in unknown:
            lines.append(
                f"  - {r['name']} 每10股{r['cash_per10']:g}元 "
                f"→ 预估{r['total']:.0f}元（{r['status']}）"
            )

    if no_div:
        lines.append("")
        lines.append(f"无分红 {len(no_div)}只")
        lines.append(f"  {', '.join(no_div[:6])}")

    lines.append("")
    lines.append("> 东财 2026年分红方案 | 未含税 | 分红再投=复利加速")

    push(f"分红金额 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 全年预估{total_cash:.0f}元")


if __name__ == "__main__":
    main()
