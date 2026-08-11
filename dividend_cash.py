"""
分红金额预测 v7
查已实施分红（2026年） → 全年已收+待收
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_implemented_dividends(codes):
    """东财 → 查已实施的分红（过去+未来都取）"""
    results = {}
    for code in codes:
        try:
            r = requests.get(
                "https://datacenter.eastmoney.com/securities/api/v1/get",
                params={
                    "reportName": "RPT_DMSK_FN_EXRW",
                    "columns": "ALL",
                    "filter": f'(SECURITY_CODE="{code}")',
                    "pageNumber": 1,
                    "pageSize": 3,
                    "sortTypes": -1,
                    "sortColumns": "EX_DIVIDEND_DATE",
                },
                timeout=15,
                headers={"Referer": "https://data.eastmoney.com/"}
            )
            data = r.json()
            if data.get("success") and data.get("result"):
                items = data["result"].get("data") or []
                for item in items:
                    cash = item.get("CASH_DIVIDEND_RATIO")
                    if cash is not None:
                        results[code] = {
                            "name": item.get("SECURITY_NAME_ABBR", code),
                            "cash_per10": cash,
                            "ex_date": item.get("EX_DIVIDEND_DATE"),
                            "pay_date": item.get("PAYMENT_DATE"),
                            "reg_date": item.get("REGISTRATION_DATE"),
                        }
                        break  # 取最新一条
        except Exception as e:
            print(f"  {code} 失败: {e}")
    return results


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
    print(f"[START] 分红金额预测 v7 {today_str}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    print(f"  逐只查询 {len(hold_codes)} 只...")
    div_data = get_implemented_dividends(hold_codes)
    print(f"  获取 {len(div_data)} 只有数据")

    received = []
    pending = []
    upcoming = []
    no_div = []
    total_received = 0
    total_pending = 0
    total_upcoming = 0

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)
        cost = v.get("cost", 0)

        d = div_data.get(code)
        if not d or not d["cash_per10"]:
            no_div.append(name)
            continue

        cash_per10 = d["cash_per10"]
        total = shares * cash_per10 / 10
        ex_date = d.get("ex_date") or ""
        pay_date = d.get("pay_date") or ""

        if pay_date and pay_date <= today_str:
            received.append((name, cash_per10, total, pay_date))
            total_received += total
        elif ex_date and ex_date <= today_str:
            pending.append((name, cash_per10, total, pay_date or "待定"))
            total_pending += total
        else:
            upcoming.append((name, cash_per10, total, ex_date or "待定", pay_date or "待定"))
            total_upcoming += total

    total_all = total_received + total_pending + total_upcoming

    lines = [
        f"分红金额 {now:%m}.{now:%d}",
        f"持仓{len(hold_codes)}只 | 全年预估{total_all/10000:.2f}万",
    ]

    if received:
        lines.append("")
        lines.append(f"✅ 已到账 {total_received/10000:.2f}万")
        for n, c, t, d in received:
            lines.append(f"  - {n} {c:g}/10股 = {t:.0f}元 ({d})")

    if pending:
        lines.append("")
        lines.append(f"⏳ 已除权待收款 {total_pending/10000:.2f}万")
        for n, c, t, d in pending:
            lines.append(f"  - {n} {t:.0f}元 → {d}")

    if upcoming:
        lines.append("")
        lines.append(f"📅 待实施 {total_upcoming/10000:.2f}万")
        for n, c, t, ex, pay in upcoming:
            lines.append(f"  - {n} {c:g}/10股 = {t:.0f}元 → 除权{ex}")

    if no_div:
        lines.append("")
        lines.append(f"今年无分红 {len(no_div)}只")
        lines.append(f"  {', '.join(no_div[:6])}")

    if not received and not pending and not upcoming:
        lines.append("")
        lines.append("8月是A股分红真空期（年报分红5-7月已结束，半年报10月才开始）")

    lines.append("")
    lines.append("> 东财除权除息 | 已收益=落袋金额")

    push(f"分红金额 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 总计{total_all:.0f}元")


if __name__ == "__main__":
    main()
