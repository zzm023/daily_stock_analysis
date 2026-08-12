"""
Tushare 公用量数据层 v1-debug
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
    print(f"  [{api_name}] code={data.get('code')} msg={data.get('msg')}")
    if data.get("code") != 0:
        print(f"  → params={params}")
        return []
    items = data["data"]["items"]
    if items:
        print(f"  → {len(items)}行 首行: {items[0]}")
    else:
        print(f"  → 0行  fields={data['data'].get('fields')}")
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
    """取最新年报净利润同比"""
    ts_codes = [_to_ts_code(c) for c in codes]
    cur = {}
    prev = {}

    for year, store in [("20251231", cur), ("20241231", prev)]:
        for i in range(0, len(ts_codes), 30):
            batch = ts_codes[i:i+30]
            rows = _call("income", {
                "ts_code": ",".join(batch),
                "end_date": year,
            }, "ts_code,end_date,n_income_attr_p")
            for row in rows:
                code = _from_ts_code(row[0])
                if row[2]:
                    store[code] = float(row[2])
            if i + 30 < len(ts_codes):
                time.sleep(0.3)

    result = {}
    for code in codes:
        c = cur.get(code)
        p = prev.get(code)
        if c and p and p != 0:
            result[code] = round((c - p) / abs(p) * 100, 1)

    return result


def get_dividends(codes):
    """取最新分红"""
    ts_codes = [_to_ts_code(c) for c in codes]
    result = {}

    for i in range(0, len(ts_codes), 20):
        batch = ts_codes[i:i+20]
        rows = _call("dividend", {
            "ts_code": ",".join(batch),
        }, "ts_code,cash_div,end_date")
        for row in rows:
            code = _from_ts_code(row[0])
            if code not in result and row[1]:
                result[code] = float(row[1])
        if i + 20 < len(ts_codes):
            time.sleep(0.3)

    return result
