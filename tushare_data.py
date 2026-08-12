"""
Tushare 公用数据层 v1-debug3
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
    if data.get("code") != 0:
        return []
    return data["data"]["items"]


def auto_whitelist():
    ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
    requests.post("https://api.tushare.pro", json={
        "api_name": "ip_whitelist",
        "token": TOKEN,
        "params": {"ip": ip},
    }, timeout=10)


def _to_ts_code(code):
    if "." in code:
        return code
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def _from_ts_code(ts_code):
    return ts_code.split(".")[0]


def get_profit_growth(codes):
    result = {}
    for code in codes:
        ts = _to_ts_code(code)
        rows = _call("income", {
            "ts_code": ts,
            "end_date": "20251231",
        }, "ts_code,end_date,n_income_attr_p")
        if not rows:
            print(f"  income {code}: 无数据")
            continue
        # 只取年报
        annual = {}
        for row in rows:
            end_date = row[1]
            val = row[2]
            if not val or not end_date.endswith("1231"):
                continue
            year = end_date[:4]
            if year not in annual:
                annual[year] = float(val)
        years = sorted(annual.keys(), reverse=True)
        if len(years) >= 2:
            latest = annual[years[0]]
            prev = annual[years[1]]
            if prev != 0:
                result[code] = round((latest - prev) / abs(prev) * 100, 1)
        if code not in result:
            print(f"  income {code}: {len(years)}年年报")
        time.sleep(0.12)
    return result


def get_dividends(codes):
    result = {}
    for code in codes:
        ts = _to_ts_code(code)
        rows = _call("dividend", {
            "ts_code": ts,
        }, "ts_code,cash_div,stk_div,end_date")
        if not rows:
            print(f"  dividend {code}: 无数据")
            continue
        best_val = 0
        best_year = ""
        for row in rows:
            cash_div = row[1]
            end_date = row[2]
            if not cash_div or not end_date.endswith("1231"):
                continue
            val = float(cash_div)
            if val > 0 and end_date[:4] > best_year:
                best_year = end_date[:4]
                best_val = val
        if best_val > 0:
            result[code] = best_val
        else:
            print(f"  dividend {code}: 无有效分红")
        time.sleep(0.12)
    return result
