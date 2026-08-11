"""
利润缓存 v1
东财年度/季度报表 → 利润增速 → JSON缓存
health_check / signal_confluence 直接读缓存
"""
import os
import json
import requests
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
CACHE_FILE = Path(__file__).parent / "profit_cache.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_profit_from_datacenter(code):
    """东财数据中心 → 最新年报净利润增速"""
    try:
        r = requests.get(
            "https://datacenter.eastmoney.com/securities/api/v1/get",
            params={
                "reportName": "RPT_DMSK_FN_MAININDICATOR",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{code}")(REPORT_DATE="2025-12-31")',
                "pageNumber": 1,
                "pageSize": 1,
                "sortTypes": -1,
                "sortColumns": "REPORT_DATE",
            },
            timeout=15,
            headers={
                "Referer": "https://data.eastmoney.com/",
                "User-Agent": "Mozilla/5.0",
            }
        )
        data = r.json()
        if data.get("success") and data.get("result"):
            items = data["result"].get("data") or []
            if items:
                item = items[0]
                return {
                    "rev_yoy": item.get("TOTAL_OPERATE_INCOME_YOY"),
                    "profit_yoy": item.get("PARENT_NETPROFIT_YOY"),
                    "report_date": item.get("REPORT_DATE","2025-12-31"),
                }
    except Exception:
        pass
    return None


def get_latest_quarter(code):
    """最新季度增长率（替补年报）"""
    try:
        r = requests.get(
            "https://datacenter.eastmoney.com/securities/api/v1/get",
            params={
                "reportName": "RPT_DMSK_FN_MAININDICATOR",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageNumber": 1,
                "pageSize": 1,
                "sortTypes": -1,
                "sortColumns": "REPORT_DATE",
            },
            timeout=15,
            headers={
                "Referer": "https://data.eastmoney.com/",
                "User-Agent": "Mozilla/5.0",
            }
        )
        data = r.json()
        if data.get("success") and data.get("result"):
            items = data["result"].get("data") or []
            if items:
                item = items[0]
                return {
                    "rev_yoy": item.get("TOTAL_OPERATE_INCOME_YOY"),
                    "profit_yoy": item.get("PARENT_NETPROFIT_YOY"),
                    "report_date": item.get("REPORT_DATE","?"),
                }
    except Exception:
        pass
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
    print(f"[START] 利润缓存 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    codes = set()
    for c in trigger:
        if isinstance(trigger.get(c), dict):
            codes.add(c)
    for c in hold:
        if c != "cash" and isinstance(hold.get(c), dict):
            codes.add(c)

    # 已有缓存
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

    hit = 0
    miss = 0
    for code in sorted(codes):
        if code in cache and cache[code].get("profit_yoy") is not None:
            hit += 1
            continue

        result = get_profit_from_datacenter(code)
        if not result or result.get("profit_yoy") is None:
            result = get_latest_quarter(code)

        if result:
            cache[code] = result
            miss += 1
        else:
            cache[code] = {"profit_yoy": None, "rev_yoy": None, "report_date": "?"}
            miss += 1

        print(f"  {code} → profit_yoy={cache[code].get('profit_yoy')}")
        time.sleep(0.3)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # 统计
    total = len(codes)
    ok = sum(1 for c in codes if cache.get(c, {}).get("profit_yoy") is not None)
    print(f"[DONE] {total}只 获取{ok}只 新增{miss}只")

    lines = [
        f"利润缓存 {now:%m}.{now:%d}",
        f"扫描{total}只 | 成功{ok}只 | 新增{miss}只",
    ]

    still_miss = [c for c in sorted(codes) if cache.get(c, {}).get("profit_yoy") is None]
    if still_miss:
        names = []
        for c in still_miss:
            t = trigger.get(c, {})
            names.append(t.get("name", c) if isinstance(t, dict) else c)
        lines.append("")
        lines.append(f"⚠️ 仍缺失 {len(still_miss)}只")
        lines.append(f"  {', '.join(names[:10])}")

    lines.append("")
    lines.append("> 年报+最新季报 | 自动缓存供九宫格/共振读取")

    push(f"利润缓存 {now:%m}.{now:%d}", "\n".join(lines))


if __name__ == "__main__":
    main()
