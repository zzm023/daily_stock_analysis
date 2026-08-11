"""
利润缓存 v2
新浪财报 → 营收/利润同比 → JSON缓存
"""
import os
import json
import requests
import re
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
CACHE_FILE = Path(__file__).parent / "profit_cache.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_profit_sina(code):
    """新浪财报 → 最新年报净利润增速"""
    # sina 财报接口
    url = (
        f"https://money.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary"
        f"/stockid/{code}/displaytype/4.phtml"
    )
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "gb2312"
        html = r.text

        # 找最近一个有数据的年份
        # 匹配模式: <td>2025-12-31</td>...<td>净利润(万元)</td>...数字
        years = re.findall(r'(\d{4})-12-31', html)
        if not years:
            return None

        latest_year = max(years)

        # 解析年度净利润数据表
        # 找 "一、营业总收入" 和 "四、净利润"
        # 简化: 找包含 latest_year 的行块，提取关键数字

        # 更可靠的方式: 找营收增长率
        # 尝试匹配利润表中的数字
        rev_pattern = re.compile(
            rf'{latest_year}-12-31.*?营业收入.*?<td[^>]*>([-\d,.]+)</td>',
            re.DOTALL
        )
        profit_pattern = re.compile(
            rf'{latest_year}-12-31.*?净利润.*?<td[^>]*>([-\d,.]+)</td>',
            re.DOTALL
        )

        # 直接用简化方法：匹配两个连续年份的数据
        year_pattern = re.compile(rf'{latest_year}-12-31.*?{int(latest_year)-1}-12-31', re.DOTALL)

        return None  # 太复杂，换思路
    except Exception:
        return None


def get_profit_eastmoney_dc(code):
    """批量取东财所有财报 → 找最新两条年报算增速"""
    try:
        r = requests.get(
            "https://datacenter.eastmoney.com/securities/api/v1/get",
            params={
                "reportName": "RPT_LICO_FN_CPD",
                "columns": "SECURITY_CODE,NOTICE_DATE,REPORT_DATE,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT",
                "filter": f'(SECURITY_TYPE_CODE="058001001")',
                "pageNumber": 1,
                "pageSize": 500,
                "sortTypes": -1,
                "sortColumns": "NOTICE_DATE",
            },
            timeout=30,
            headers={"Referer": "https://data.eastmoney.com/", "User-Agent": "Mozilla/5.0"}
        )
        data = r.json()
        if data.get("success") and data.get("result"):
            items = data["result"].get("data") or []
            print(f"  批量取 {len(items)} 条")
            # 按代码分组 → 找每只最新两条年报
            by_code = {}
            for item in items:
                code = item.get("SECURITY_CODE","")
                rdate = item.get("REPORT_DATE","")
                if not code or "-12-31" not in rdate:
                    continue
                if code not in by_code:
                    by_code[code] = []
                by_code[code].append(item)

            results = {}
            for code, rows in by_code.items():
                rows.sort(key=lambda x: x.get("REPORT_DATE",""), reverse=True)
                if len(rows) >= 2:
                    cur = rows[0]
                    prev = rows[1]
                    cur_profit = cur.get("PARENT_NETPROFIT")
                    prev_profit = prev.get("PARENT_NETPROFIT")
                    cur_rev = cur.get("TOTAL_OPERATE_INCOME")
                    prev_rev = prev.get("TOTAL_OPERATE_INCOME")
                    if cur_profit and prev_profit and prev_profit != 0:
                        profit_yoy = (cur_profit - prev_profit) / abs(prev_profit) * 100
                    else:
                        profit_yoy = None
                    if cur_rev and prev_rev and prev_rev != 0:
                        rev_yoy = (cur_rev - prev_rev) / abs(prev_rev) * 100
                    else:
                        rev_yoy = None
                    results[code] = {
                        "profit_yoy": round(profit_yoy, 1) if profit_yoy is not None else None,
                        "rev_yoy": round(rev_yoy, 1) if rev_yoy is not None else None,
                        "report_date": rows[0].get("REPORT_DATE","?"),
                    }
            return results
    except Exception as e:
        print(f"  dc失败: {e}")
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
    print(f"[START] 利润缓存 v2 {now:%Y-%m-%d}")

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

    # 批量取
    all_data = get_profit_eastmoney_dc(None)
    if not all_data:
        print("  无数据")
        return

    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

    hit = 0
    miss = 0
    for code in sorted(codes):
        d = all_data.get(code)
        if d:
            cache[code] = d
            if d.get("profit_yoy") is not None:
                hit += 1
            else:
                miss += 1
        else:
            if code not in cache:
                cache[code] = {"profit_yoy": None, "rev_yoy": None, "report_date": "?"}
                miss += 1
            else:
                hit += 1
        if code in all_data:
            print(f"  {code} → profit_yoy={all_data[code].get('profit_yoy')}")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    total = len(codes)
    ok = sum(1 for c in codes if cache.get(c, {}).get("profit_yoy") is not None)
    lines = [
        f"利润缓存 {now:%m}.{now:%d}",
        f"扫描{total}只 | 成功{ok}只 | 新增{hit}只",
    ]

    still_miss = [c for c in sorted(codes) if cache.get(c, {}).get("profit_yoy") is None]
    if still_miss:
        names = []
        for c in still_miss:
            t = trigger.get(c, {})
            names.append(t.get("name", c) if isinstance(t, dict) else c)
        lines.append("")
        lines.append(f"⚠️ 仍缺失 {len(still_miss)}只 {', '.join(names[:8])}")

    lines.append("")
    lines.append("> RPT_LICO_FN_CPD批量 | 年报同比")

    push(f"利润缓存 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
