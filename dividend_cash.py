"""
分红金额预测 v6
columns=ALL + 不加年份过滤 → 全量取再筛
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_all_dividends():
    """columns=ALL 全量 → 再筛持仓"""
    try:
        r = requests.get(
            "https://datacenter.eastmoney.com/securities/api/v1/get",
            params={
                "reportName": "RPT_DMSK_FN_EXRW",
                "columns": "ALL",
                "pageNumber": 1,
                "pageSize": 200,
                "sortTypes": -1,
                "sortColumns": "EX_DIVIDEND_DATE",
            },
            timeout=30,
            headers={"Referer": "https://data.eastmoney.com/"}
        )
        print(f"  status={r.status_code}")
        raw = r.text[:300]
        print(f"  raw[:300]={raw}")
        data = r.json()
        print(f"  success={data.get('success')} "
              f"count={data.get('result',{}).get('count',0)}")
        items = (data.get("result") or {}).get("data") or []
        results = {}
        for item in items:
            code = item.get("SECURITY_CODE", "")
            results[code] = {
                "name": item.get("SECURITY_NAME_ABBR", code),
                "cash_per10": item.get("CASH_DIVIDEND_RATIO"),
                "ex_date": item.get("EX_DIVIDEND_DATE"),
                "pay_date": item.get("PAYMENT_DATE"),
                "reg_date": item.get("REGISTRATION_DATE"),
            }
        print(f"  总{len(results)}只")
        return results
    except Exception as e:
        print(f"  失败: {e}")
        if 'r' in dir():
            print(f"  body: {r.text[:500]}")
        return {}


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("  无 PUSHPLUS_TOKEN")
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
        print("  推送成功")
    except Exception as e:
        print(f"  推送失败: {e}")


def main():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    print(f"[START] 分红金额预测 v6 {today_str}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    print(f"  全量取分红数据...")
    all_div = get_all_dividends()
    print(f"  持仓 {len(hold_codes)} 只，匹配中...")

    rows = []
    total_cash = 0
    no_div = []

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)

        d = all_div.get(code)
        if not d or not d["cash_per10"]:
            no_div.append(name)
            print(f"    {name} → 无分红")
            continue

        cash_per10 = d["cash_per10"]
        total = shares * cash_per10 / 10
        total_cash += total
        rows.append({
            "name": name, "shares": shares,
            "cash_per10": cash_per10, "total": total,
            "ex_date": d.get("ex_date", "?"),
            "pay_date": d.get("pay_date", "?"),
        })
        print(f"    {name} → {cash_per10}/10股 = {total:.0f}元")

    rows.sort(key=lambda x: x["ex_date"] if x["ex_date"] and x["ex_date"] != "?" else "9999")

    lines = [
        f"分红金额预测 {now:%m}.{now:%d}",
        f"持仓{len(hold_codes)}只 | 有分红{len(rows)}只 "
        f"| 预估{total_cash/10000:.2f}万",
    ]

    received = [r for r in rows
                if r["pay_date"] and r["pay_date"] <= today_str]
    pending = [r for r in rows
               if r["ex_date"] and r["ex_date"] <= today_str
               and r["pay_date"] and r["pay_date"] > today_str]
    upcoming = [r for r in rows
                if r["ex_date"] and r["ex_date"] > today_str]

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

    if no_div:
        lines.append(""); lines.append(f"无分红 {len(no_div)}只")
        lines.append(f"  {', '.join(no_div[:6])}")

    lines.append("")
    lines.append("> 东财除权除息表 | 未含税")

    push(f"分红金额 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 全年预估{total_cash:.0f}元")


if __name__ == "__main__":
    main()
