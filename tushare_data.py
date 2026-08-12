"""
Tushare 公用数据层 v1
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
            continue
        annual = {}
        for row in rows:
            # row: [ts_code, end_date, n_income_attr_p]
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
    ts_codes = [_to_ts_code(c) for c in codes]
    all_rows = []

    for i in range(0, len(ts_codes), 10):
        batch = ts_codes[i:i+10]
        rows = _call("dividend", {
            "ts_code": ",".join(batch),
        }, "ts_code,cash_div,stk_div,end_date")
        all_rows.extend(rows)
        print(f"    dividend batch{i//10}: {len(rows)} rows")
        if rows:
            print(f"      首行: {rows[0]}")
        if i + 10 < len(ts_codes):
            time.sleep(0.5)

    # 同一年多条求和
    year_total = {}
    for row in all_rows:
        code = _from_ts_code(row[0])
        cash_div = row[1]
        # row[3] = end_date (列序: ts_code, cash_div, stk_div, end_date)
        ed = str(int(row[3]))
        if not cash_div or not ed.endswith("1231"):
            continue
        val = float(cash_div)
        if val <= 0:
            continue
        year = ed[:4]
        key = (code, year)
        year_total[key] = year_total.get(key, 0) + val

    print(f"    year_total keys: {len(year_total)}, sample: {dict(list(year_total.items())[:5])}")

    # 取最新年份
    result = {}
    for code in codes:
        best_year = ""
        best_val = 0
        for (c, y), v in year_total.items():
            if c == code and y > best_year:
                best_year = y
                best_val = v
        if best_val > 0:
            result[code] = round(best_val, 3)

    return result
