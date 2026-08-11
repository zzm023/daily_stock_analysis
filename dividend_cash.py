"""
分红金额预测 v4
去 REPORT_YEAR + 加调试 → 先看 API 到底返回什么
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def test_api(code):
    """单只调试"""
    for yr in [None, "2025", "2026"]:
        if yr:
            ft = f'(SECURITY_CODE="{code}")(REPORT_YEAR="{yr}")'
        else:
            ft = f'(SECURITY_CODE="{code}")'
        try:
            r = requests.get(
                "https://datacenter.eastmoney.com/securities/api/v1/get",
                params={
                    "reportName": "RPT_DMSK_FN_EXRW",
                    "columns": "ALL",
                    "filter": ft,
                    "pageNumber": 1,
                    "pageSize": 5,
                    "sortTypes": -1,
                    "sortColumns": "EX_DIVIDEND_DATE",
                },
                timeout=15,
                headers={"Referer": "https://data.eastmoney.com/"}
            )
            data = r.json()
            success = data.get("success")
            total = data.get("result", {}).get("count", 0) if data.get("result") else 0
            items = data.get("result", {}).get("data") or [] if data.get("result") else []
            print(f"  yr={yr} success={success} total={total}")
            if items:
                for item in items[:2]:
                    print(f"    {item.get('SECURITY_NAME_ABBR')} "
                          f"分红{item.get('CASH_DIVIDEND_RATIO')} "
                          f"除权{item.get('EX_DIVIDEND_DATE')} "
                          f"到账{item.get('PAYMENT_DATE')}")
                return items
        except Exception as e:
            print(f"  yr={yr} 失败: {e}")
    return None


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
    print(f"[START] 分红金额预测 v4 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [
        c for c in hold
        if c != "cash" and isinstance(hold.get(c), dict)
    ]

    # 先调第一只
    test_code = hold_codes[0] if hold_codes else "002027"
    test_name = hold.get(test_code, {}).get("name", test_code) if test_code in hold else test_code
    print(f"  调试 {test_name}({test_code}):")
    test_api(test_code)

    if hold_codes and len(hold_codes) > 1:
        test_code2 = hold_codes[1]
        test_name2 = hold.get(test_code2, {}).get("name", test_code2)
        print(f"\n  调试 {test_name2}({test_code2}):")
        test_api(test_code2)

    lines = [
        f"分红金额 v4 调试 {now:%m}.{now:%d}",
        f"测试 {test_name} → 看 Actions 日志",
    ]
    push(f"分红调试 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
