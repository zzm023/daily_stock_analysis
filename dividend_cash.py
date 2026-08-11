"""
分红金额预测 v10
优先 API → 失败兜底手工 → 每半年更新即可
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 兜底数据（API失败时用，半年更新一次）
FALLBACK = {
    "002027": (0.33, "2026-06-15", "2026-06-16", "2025年报"),
    "600690": (0.38, "2026-07-10", "2026-07-11", "2025年报"),
    "000708": (0.55, "2026-06-20", "2026-06-23", "2025年报"),
    "600845": (0.50, "2026-06-05", "2026-06-06", "2025年报"),
    "000157": (0.16, "2026-07-25", "2026-07-28", "2025年报"),
    "002601": (0.40, "2026-05-15", "2026-05-16", "2025年报"),
    "600161": (0.05, "", "", "2025年报"),
    "300498": (0.20, "", "", "2025年报"),
    "002747": (0.00, "", "", "无分红"),
}


def api_get_all():
    """API 全量取 → 优先使用"""
    results = {}
    try:
        r = requests.get(
            "https://datacenter.eastmoney.com/securities/api/v1/get",
            params={
                "reportName": "RPT_DMSK_FN_EXRW",
                "columns": "ALL",
                "pageNumber": 1,
                "pageSize": 500,
                "sortTypes": -1,
                "sortColumns": "EX_DIVIDEND_DATE",
            },
            timeout=30,
            headers={"Referer": "https://data.eastmoney.com/"}
        )
        data = r.json()
        if data.get("success") and data.get("result"):
            items = data["result"].get("data") or []
            for item in items:
                code = item.get("SECURITY_CODE", "")
                cash = item.get("CASH_DIVIDEND_RATIO")
                if code and cash:
                    results[code] = (
                        cash,
                        item.get("EX_DIVIDEND_DATE") or "",
                        item.get("PAYMENT_DATE") or "",
                        "API",
                    )
            print(f"  API 取到 {len(results)} 只")
        return results
    except Exception as e:
        print(f"  API 失败: {e}")
        return {}


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
    print(f"[START] 分红金额 v10 {today_str}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    # 尝试 API
    api_data = api_get_all()
    use_api = len(api_data) >= 2

    received, pending, upcoming, no_div = [], [], [], []
    total_received = total_pending = total_upcoming = 0

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)

        entry = api_data.get(code) if use_api else FALLBACK.get(code)
        if entry is None:
            continue

        dps = float(entry[0]) if len(entry) >= 1 else 0
        ex_date = str(entry[1]) if len(entry) >= 2 else ""
        pay_date = str(entry[2]) if len(entry) >= 3 else ""
        source = str(entry[3]) if len(entry) >= 4 else "?"

        total = shares * dps

        if dps == 0:
            no_div.append(name)
            continue

        if pay_date and pay_date <= today_str:
            received.append((name, dps, total, pay_date, source))
            total_received += total
        elif ex_date and ex_date <= today_str:
            pending.append((name, dps, total, pay_date or "?", source))
            total_pending += total
        else:
            upcoming.append((name, dps, total, ex_date or "?", pay_date or "?", source))
            total_upcoming += total

    total_all = total_received + total_pending + total_upcoming

    lines = [
        f"分红金额 {now:%m}.{now:%d}",
        f"持仓{len(hold_codes)}只 | 全年{total_all/10000:.2f}万"
        f"{' [API]' if use_api else ' [手工]'}",
    ]

    if received:
        lines.append("")
        lines.append(f"✅ 已到账 {total_received/10000:.2f}万")
        for n, dps, t, d, src in received:
            lines.append(f"  - {n} {dps}/股 = {t:.0f}元 ({d}) [{src}]")

    if pending:
        lines.append("")
        lines.append(f"⏳ 已除权待收款 {total_pending/10000:.2f}万")
        for n, dps, t, d, src in pending:
            lines.append(f"  - {n} {t:.0f}元 → {d} [{src}]")

    if upcoming:
        lines.append("")
        lines.append(f"📅 待除权 {total_upcoming/10000:.2f}万")
        for n, dps, t, ex, pay, src in upcoming:
            lines.append(f"  - {n} {dps}/股 = {t:.0f}元 → {ex} [{src}]")

    if no_div:
        lines.append("")
        lines.append(f"无分红 {len(no_div)}只  {', '.join(no_div[:6])}")

    lines.append("")
    lines.append("> 分红一年公告2次 | 手工数据每半年核对一次即可")

    push(f"分红金额 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 总计{total_all:.0f}元 来源={'API' if use_api else '手工'}")


if __name__ == "__main__":
    main()
