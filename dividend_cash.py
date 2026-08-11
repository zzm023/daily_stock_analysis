"""
分红金额预测 v8
全量取 ALL → Python筛 | REPORT_YEAR="2025"
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_all_dividends(pages=5):
    """全量取 → 再筛"""
    all_items = []
    for page in range(1, pages + 1):
        try:
            r = requests.get(
                "https://datacenter.eastmoney.com/securities/api/v1/get",
                params={
                    "reportName": "RPT_DMSK_FN_EXRW",
                    "columns": "ALL",
                    "filter": '(REPORT_YEAR="2025")',
                    "pageNumber": page,
                    "pageSize": 200,
                    "sortTypes": -1,
                    "sortColumns": "EX_DIVIDEND_DATE",
                },
                timeout=30,
                headers={"Referer": "https://data.eastmoney.com/"}
            )
            data = r.json()
            if data.get("success") and data.get("result"):
                items = data["result"].get("data") or []
                if not items:
                    break
                all_items.extend(items)
                print(f"  第{page}页 → {len(items)}条 (累计{len(all_items)})")
                total = data["result"].get("count", 0)
                if len(all_items) >= total:
                    break
            else:
                print(f"  第{page}页无数据 success={data.get('success')}")
                break
        except Exception as e:
            print(f"  第{page}页失败: {e}")
            break

    results = {}
    for item in all_items:
        code = item.get("SECURITY_CODE", "")
        cash = item.get("CASH_DIVIDEND_RATIO")
        if code and cash:
            results[code] = {
                "name": item.get("SECURITY_NAME_ABBR", code),
                "cash_per10": cash,
                "ex_date": item.get("EX_DIVIDEND_DATE", ""),
                "pay_date": item.get("PAYMENT_DATE", ""),
            }
    print(f"  全量 {len(all_items)} 条 → 去重 {len(results)} 只")
    return results


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
    today_str = now.strftime("%Y-%m-%d")
    print(f"[START] 分红金额预测 v8 {today_str}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    print(f"  全量取分红...")
    all_div = get_all_dividends(pages=5)
    print(f"  匹配持仓 {len(hold_codes)} 只...")

    received, pending, upcoming, no_div = [], [], [], []
    total_received = total_pending = total_upcoming = 0

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)

        d = all_div.get(code)
        if not d or not d["cash_per10"]:
            no_div.append(name)
            continue

        cash_per10 = d["cash_per10"]
        total = shares * cash_per10 / 10
        ex_date = d.get("ex_date") or ""
        pay_date = d.get("pay_date") or ""

        print(f"    {name} {cash_per10}/10股 = {total:.0f}元 ex={ex_date} pay={pay_date}")

        if pay_date and pay_date <= today_str:
            received.append((name, cash_per10, total, pay_date))
            total_received += total
        elif ex_date and ex_date <= today_str:
            pending.append((name, cash_per10, total, pay_date or "?"))
            total_pending += total
        else:
            upcoming.append((name, cash_per10, total, ex_date or "?", pay_date or "?"))
            total_upcoming += total

    total_all = total_received + total_pending + total_upcoming

    lines = [
        f"分红金额 {now:%m}.{now:%d}",
        f"持仓{len(hold_codes)}只 | 全年{total_all/10000:.2f}万",
    ]

    if received:
        lines.append(""); lines.append(f"✅ 已到账 {total_received/10000:.2f}万")
        for n, c, t, d in received:
            lines.append(f"  - {n} {c:g}/10股 = {t:.0f}元 ({d})")

    if pending:
        lines.append(""); lines.append(f"⏳ 已除权待收款 {total_pending/10000:.2f}万")
        for n, c, t, d in pending:
            lines.append(f"  - {n} {t:.0f}元 → {d}")

    if upcoming:
        lines.append(""); lines.append(f"📅 未来除权 {total_upcoming/10000:.2f}万")
        for n, c, t, ex, pay in upcoming:
            lines.append(f"  - {n} {c:g}/10股 = {t:.0f}元 → {ex}")

    if no_div:
        lines.append(""); lines.append(f"无分红 {len(no_div)}只")
        lines.append(f"  {', '.join(no_div[:6])}")

    if not received and not pending and not upcoming:
        lines.append(""); lines.append("8月A股分红真空期（年报分红5-7月已结束）")

    lines.append(""); lines.append("> 东财 2025年报分红 | 已收益=落袋金额")

    push(f"分红金额 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 总计{total_all:.0f}元")


if __name__ == "__main__":
    main()
