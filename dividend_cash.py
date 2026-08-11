"""
分红金额预测 v3
修正 URL + 用已验证的 API 参数
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
    """东财 RPT_DMSK_FN_EXRW → 2025年报分红(2026实施)"""
    code_filter = ",".join(f'"{c}"' for c in codes)
    try:
        r = requests.get(
            "https://datacenter.eastmoney.com/securities/api/v1/get",
            params={
                "reportName": "RPT_DMSK_FN_EXRW",
                "columns": (
                    "SECURITY_CODE,SECURITY_NAME_ABBR,"
                    "CASH_DIVIDEND_RATIO,BONUS_SHARE_RATIO,"
                    "TRANSFER_SHARE_RATIO,"
                    "EX_DIVIDEND_DATE,PAYMENT_DATE,"
                    "REGISTRATION_DATE,PLAN_EXPLAIN"
                ),
                "filter": (
                    f'(SECURITY_CODE in ({code_filter}))'
                    f'(REPORT_YEAR="2025")'
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
        print(f"  API返回 success={data.get('success')} result={bool(data.get('result'))}")
        results = {}
        if data.get("success") and data.get("result"):
            items = data["result"].get("data") or []
            print(f"  共 {len(items)} 条记录")
            for item in items:
                code = item.get("SECURITY_CODE", "")
                results[code] = {
                    "name": item.get("SECURITY_NAME_ABBR", code),
                    "cash_per10": item.get("CASH_DIVIDEND_RATIO"),
                    "bonus_share": item.get("BONUS_SHARE_RATIO"),
                    "transfer": item.get("TRANSFER_SHARE_RATIO"),
                    "ex_date": item.get("EX_DIVIDEND_DATE"),
                    "pay_date": item.get("PAYMENT_DATE"),
                    "reg_date": item.get("REGISTRATION_DATE"),
                    "plan": item.get("PLAN_EXPLAIN", ""),
                }
        return results
    except Exception as e:
        print(f"  分红数据获取失败: {e}")
        return {}


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("  PUSHPLUS_TOKEN 未设置")
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
        print(f"  推送: {resp.status_code}")
    except Exception as e:
        print(f"  推送失败: {e}")


def main():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    print(f"[START] 分红金额预测 v3 {today_str}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    print(f"  持仓 {len(hold_codes)} 只: {hold_codes}")
    div_data = get_dividends(hold_codes)
    print(f"  获取 {len(div_data)} 只有数据")

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
            "plan": d.get("plan", ""),
        })

    rows.sort(key=lambda x: (
        x["ex_date"] if x["ex_date"] and x["ex_date"] != "?" else "9999"
    ))

    lines = [
        f"分红金额预测 {now:%m}.{now:%d}",
        f"2025年报分红 | 持仓{len(hold_codes)}只 | "
        f"有分红{len(rows)}只 | 预估{total_cash/10000:.2f}万",
    ]

    received = [r for r in rows
                if r["pay_date"] and r["pay_date"] <= today_str]
    pending = [r for r in rows
               if r["ex_date"] and r["ex_date"] <= today_str
               and r["pay_date"] and r["pay_date"] > today_str]
    upcoming = [r for r in rows
                if r["ex_date"] and r["ex_date"] > today_str]
    unknown = [r for r in rows
               if not r["ex_date"] or r["ex_date"] == "?"]

    if received:
        lines.append(""); lines.append(f"已到账 {len(received)}只")
        for r in received:
            lines.append(f"  - {r['name']} {r['cash_per10']:g}/10股 = {r['total']:.0f}元 ✓")

    if pending:
        lines.append(""); lines.append(f"已除权待收款 {len(pending)}只")
        for r in pending:
            lines.append(f"  - {r['name']} {r['total']:.0f}元 → {r['pay_date']}")

    if upcoming:
        lines.append(""); lines.append(f"即将除权 {len(upcoming)}只")
        for r in upcoming:
            lines.append(f"  - {r['name']} {r['total']:.0f}元 → 除权{r['ex_date']} 到账{r['pay_date']}")

    if unknown:
        lines.append(""); lines.append(f"日期待定 {len(unknown)}只")
        for r in unknown:
            lines.append(f"  - {r['name']} 每10股{r['cash_per10']:g}元 → 预估{r['total']:.0f}元")

    if no_div:
        lines.append(""); lines.append(f"无分红 {len(no_div)}只")
        lines.append(f"  {', '.join(no_div[:6])}")

    lines.append("")
    lines.append("> 东财除权除息表 2025年报(2026实施) | 未含税")

    push(f"分红金额 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 全年预估{total_cash:.0f}元")


if __name__ == "__main__":
    main()
