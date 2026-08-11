"""
分红金额预测 v5
打印原始响应 → 看 API 到底返回什么
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def test_api_raw():
    """裸调 → 打印完整响应"""
    url = "https://datacenter.eastmoney.com/securities/api/v1/get"
    params = {
        "reportName": "RPT_DMSK_FN_EXRW",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,CASH_DIVIDEND_RATIO,EX_DIVIDEND_DATE,PAYMENT_DATE",
        "filter": '(SECURITY_CODE="600845")',
        "pageNumber": 1,
        "pageSize": 5,
        "sortTypes": -1,
        "sortColumns": "EX_DIVIDEND_DATE",
    }
    print(f"  URL: {url}")
    print(f"  params: {params}")

    try:
        r = requests.get(url, params=params, timeout=15,
                         headers={"Referer": "https://data.eastmoney.com/"})
        print(f"  status: {r.status_code}")
        print(f"  content-type: {r.headers.get('content-type', 'N/A')}")
        print(f"  body[:500]: {r.text[:500]}")
        try:
            data = r.json()
            print(f"  parsed keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            if isinstance(data, dict):
                for k, v in data.items():
                    vs = str(v)[:200]
                    print(f"    {k} = {vs}")
        except Exception as e:
            print(f"  JSON解析失败: {e}")
            print(f"  full body: {r.text[:1000]}")
    except Exception as e:
        print(f"  请求失败: {e}")


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
    print(f"[START] 分红金额预测 v5 {now:%Y-%m-%d}")

    test_api_raw()

    lines = [
        f"分红金额 v5 调试 {now:%m}.{now:%d}",
        "看 Actions 日志原始响应",
    ]
    push(f"分红调试 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
