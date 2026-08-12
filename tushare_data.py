"""
Tushare 公用数据层 v1
"""
import os, requests, json, time

TOKEN = os.environ.get("TUSHARE_TOKEN", "")


def _call(api_name, params=None, fields=""):
    payload = {"api_name": api_name, "token": TOKEN, "params": params or {}}
    if fields:
        payload["fields"] = fields
    r = requests.post("https://api.tushare.pro", json=payload, timeout=30)
    data = r.json()
    if data.get("code") != 0:
        print(f"  [{api_name}] FAIL: {data.get('msg')}")
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
            continue
        annual = {}
        for row in rows:
            ed = str(int(row[1]))
            val = row[2]
            if not val or not ed.endswith("1231"):
                continue
            year = ed[:4]
            if year not in annual:
                annual[year] = float(val)
        years = sorted(annual.keys(), reverse=True)
        if len(years) >= 2:
            latest = annual[years[0]]
            prev = annual[years[1]]
            if prev != 0:
                result[code] = round((latest - prev) / abs(prev) * 100, 1)
        time.sleep(0.12)
    return result


def get_dividends(codes):
    """
    取最新年度每股分红（同一年多条求和）
    """
    result = {}
    for code in codes:
        ts = _to_ts_code(code)
        rows = _call("dividend", {
            "ts_code": ts,
        }, "ts_code,cash_div,stk_div,end_date")
        if not rows:
            continue

        year_total = {}
        for row in rows:
            cash_div = row[1]
            ed = str(int(row[3]))
            if not cash_div or not ed.endswith("1231"):
                continue
            val = float(cash_div)
            if val <= 0:
                continue
            year = ed[:4]
            year_total[year] = year_total.get(year, 0) + val

        if year_total:
            best_year = max(year_total.keys())
            result[code] = round(year_total[best_year], 3)
        time.sleep(0.12)
    return result
