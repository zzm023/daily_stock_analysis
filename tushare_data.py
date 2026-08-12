"""
Tushare 公用数据层 v1
自动白名单 + 批量利润/分红/财报
"""
import os, requests, json, time
from pathlib import Path

TOKEN = os.environ.get("TUSHARE_TOKEN", "")
CACHE_DIR = Path(__file__).parent

def _call(api_name, params=None, fields=""):
    """通用 Tushare HTTP 调用"""
    payload = {"api_name": api_name, "token": TOKEN, "params": params or {}}
    if fields:
        payload["fields"] = fields
    r = requests.post("https://api.tushare.pro", json=payload, timeout=30)
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"{api_name}: {data.get('msg')}")
    return data["data"]["items"]


def auto_whitelist():
    """自动加当前 IP 到白名单"""
    ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
    requests.post("https://api.tushare.pro", json={
        "api_name": "ip_whitelist", "token": TOKEN,
        "params": {"ip": ip},
    }, timeout=10)


def _to_ts_code(code):
    """600036 → 600036.SH"""
    if "." in code:
        return code
    suffix = ".SH" if code.startswith("6") else ".SZ"
    return f"{code}{suffix}"


def _from_ts_code(ts_code):
    """600036.SH → 600036"""
    return ts_code.split(".")[0]


def get_profit_growth(codes):
    """
    批量取最新年报净利润同比增速
    返回 {code: profit_yoy%}
    """
    ts_codes = [_to_ts_code(c) for c in codes]
    result = {}

    for i in range(0, len(ts_codes), 30):
        batch = ts_codes[i:i+30]
        try:
            rows = _call("income", {
                "ts_code": ",".join(batch),
                "end_date": "20251231",
                "period": "20251231",
            }, "ts_code,n_income,revenue")
            # Tushare income 不直接给同比，需要年报对比
            # 策略：取2025和2024两年年报
        except:
            pass

    # 分两年取
    for year in ["20251231", "20241231"]:
        cache = {}
        for i in range(0, len(ts_codes), 30):
            batch = ts_codes[i:i+30]
            try:
                rows = _call("income", {
                    "ts_code": ",".join(batch),
                    "end_date": year,
                    "period": year,
                }, "ts_code,n_income")
                for row in rows:
                    cache[_from_ts_code(row[0])] = float(row[1]) if row[1] else None
            except:
                pass
            time.sleep(0.3)
        if year == "20251231":
            cur = cache
        else:
            prev = cache

    for code in codes:
        c = cur.get(code)
        p = prev.get(code)
        if c and p and p != 0 and c > 0 and p > 0:
            result[code] = round((c - p) / p * 100, 1)

    return result


def get_dividends(codes):
    """批量取最新年度分红(每股) → {code: dps}"""
    ts_codes = [_to_ts_code(c) for c in codes]
    result = {}

    for i in range(0, len(ts_codes), 20):
        batch = ts_codes[i:i+20]
        try:
            rows = _call("dividend", {
                "ts_code": ",".join(batch),
            }, "ts_code,stk_div,cash_div,ex_date,end_date")
            for row in rows:
                code = _from_ts_code(row[0])
                if code not in result:
                    result[code] = float(row[2]) if row[2] else 0
        except:
            pass
        time.sleep(0.3)

    return result


def get_forecasts(codes):
    """业绩预告 → {code: {profit_range, change_range, notice_date}}"""
    ts_codes = [_to_ts_code(c) for c in codes]
    result = {}

    for i in range(0, len(ts_codes), 20):
        batch = ts_codes[i:i+20]
        try:
            rows = _call("forecast", {
                "ts_code": ",".join(batch),
                "period": "20251231",
            }, "ts_code,type,p_change_min,p_change_max,notice_date,summary")
            for row in rows:
                code = _from_ts_code(row[0])
                result[code] = {
                    "type": row[1],
                    "p_change_min": float(row[2]) if row[2] else None,
                    "p_change_max": float(row[3]) if row[3] else None,
                    "notice_date": row[4],
                    "summary": row[5],
                }
        except:
            pass
        time.sleep(0.3)

    return result
