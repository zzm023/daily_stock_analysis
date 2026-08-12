"""
Tushare 公用数据层 v1-debug2
"""
import os, requests, json, time
from pathlib import Path

TOKEN = os.environ.get("TUSHARE_TOKEN", "")


def _call(api_name, params=None, fields=""):
    payload = {"api_name": api_name, "token": TOKEN, "params": params or {}}
    if fields:
        payload["fields"] = fields
    r = requests.post("https://api.tushare.pro", json=payload, timeout=30)
    data = r.json()
    code = data.get("code")
    if code != 0:
        print(f"  [{api_name}] FAIL: {data.get('msg')}")
        return []
    items = data["data"]["items"]
    print(f"  [{api_name}] {len(items)}行")
    if items:
        print(f"    首行: {items[0]}")
    return items


def auto_whitelist():
    ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
    r = requests.post("https://api.tushare.pro", json={
        "api_name": "ip_whitelist", "token": TOKEN, "params": {"ip": ip},
    }, timeout=10)
    print(f"  白名单: {r.json().get('msg')}")


def _to_ts_code(code):
    if "." in code: return code
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def _from_ts_code(ts_code):
    return ts_code.split(".")[0]


def get_profit_growth(codes):
    ts_codes = [_to_ts_code(c) for c in codes]
    all_rows = []

    for i in range(0, len(ts_codes), 10):
        batch = ts_codes[i:i+10]
        rows = _call("income", {
            "ts_code": ",".join(batch),
        }, "ts_code,end_date,n_income_attr_p")
        all_rows.extend(rows)
        if i + 10 < len(ts_codes):
            time.sleep(0.5)

    # 筛选年报
    annual = {}
    for row in all_rows:
        code = _from_ts_code(row[0])
        end_date = row[1]
        val = row[2]
        if not val or not end_date.endswith("1231"):
            continue
        year = end_date[:4]
        if code not in annual:
            annual[code] = {}
        annual[code][year] = max(annual[code].get(year, 0), float(val))

    print(f"  年报覆盖: {list(annual.keys())[:5]}...")

    result = {}
    for code in codes:
        years = annual.get(code, {})
        sorted_years = sorted(years.keys(), reverse=True)
        if len(sorted_years) < 2:
            continue
        latest = years[sorted_years[0]]
        prev = years[sorted_years[1]]
        if prev and prev != 0:
            result[code] = round((latest - prev) / abs(prev) * 100, 1)

    return result


def get_dividends(codes):
    ts_codes = [_to_ts_code(c) for c in codes]
    all_rows = []

    for i in range(0, len(ts_codes), 10):
        batch = ts_codes[i:i+10]
        rows = _call("dividend", {
            "ts_code": ",".join(batch),
        }, "ts_code,cash_div,stk_div,end_date")
        all_rows.extend(rows)
        if i + 10 < len(ts_codes):
            time.sleep(0.5)

    # 只取年度，cash_div > 0
    annual = {}
    for row in all_rows:
        code = _from_ts_code(row[0])
        cash_div = row[1]
        end_date = row[2]
        if not cash_div or not end_date.endswith("1231"):
            continue
        val = float(cash_div)
        if val <= 0:
            continue
        year = end_date[:4]
        if code not in annual or year > annual[code][0]:
            annual[code] = (year, val)

    print(f"  分红覆盖: {list(annual.keys())[:5]}...")
    return {code: val for code, (year, val) in annual.items()}
