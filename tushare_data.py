"""
Tushare 公用数据层 v1
自动白名单 + 利润同比 + 分红
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
        raise Exception(f"{api_name}: {data.get('msg')}")
    return data["data"]["items"]


def auto_whitelist():
    ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
    requests.post("https://api.tushare.pro", json={
        "api_name": "ip_whitelist", "token": TOKEN, "params": {"ip": ip},
    }, timeout=10)


def _to_ts_code(code):
    if "." in code:
        return code
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def _from_ts_code(ts_code):
    return ts_code.split(".")[0]


def get_profit_growth(codes):
    """
    取最近两年年报净利润同比
    返回 {code: profit_yoy%}
    """
    ts_codes = [_to_ts_code(c) for c in codes]
    all_rows = []

    for i in range(0, len(ts_codes), 20):
        batch = ts_codes[i:i+20]
        rows = _call("income", {
            "ts_code": ",".join(batch),
        }, "ts_code,end_date,n_income_attr_p")
        all_rows.extend(rows)
        if i + 20 < len(ts_codes):
            time.sleep(0.3)

    # 只取年报（end_date 以 1231 结尾），按股票分组
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
        # 同一年可能重复，取最大值
        annual[code][year] = max(annual[code].get(year, 0), float(val))

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
    """
    取最新年度每股分红（取最新一条 cash_div > 0 的年度记录）
    返回 {code: dps}
    """
    ts_codes = [_to_ts_code(c) for c in codes]
    all_rows = []

    for i in range(0, len(ts_codes), 20):
        batch = ts_codes[i:i+20]
        rows = _call("dividend", {
            "ts_code": ",".join(batch),
        }, "ts_code,cash_div,stk_div,end_date")
        all_rows.extend(rows)
        if i + 20 < len(ts_codes):
            time.sleep(0.3)

    # 只取年度分红（1231结尾），cash_div 有值且>0
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

    return {code: val for code, (year, val) in annual.items()}
