"""
校准 DEBUG — 只测招商银行
"""
import os, json, requests, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
TOKEN = os.environ.get("TUSHARE_TOKEN", "")


def tushare_call(api, params, fields):
    ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
    requests.post("https://api.tushare.pro", json={
        "api_name": "ip_whitelist", "token": TOKEN, "params": {"ip": ip}}, timeout=10)
    payload = {"api_name": api, "token": TOKEN, "params": params, "fields": fields}
    r = requests.post("https://api.tushare.pro", json=payload, timeout=30)
    d = r.json()
    if d.get("code") != 0:
        print(f"  FAIL: {d.get('msg')}")
        return []
    return d["data"]["items"]


# ── 招商银行 600036 ──
code = "600036"
ts = "600036.SH"

# Income
income_rows = tushare_call("income", {"ts_code": ts, "end_date": "20261231"},
                           "ts_code,end_date,total_revenue,n_income_attr_p")
print("=== INCOME RAW ===")
for r in income_rows[:5]:
    print(f"  end_date={r[1]} revenue={r[2]} profit={r[3]}")

# Daily Basic
basic_rows = tushare_call("daily_basic", {"ts_code": ts},
                          "ts_code,trade_date,total_share,total_mv")
print("\n=== DAILY_BASIC RAW ===")
for r in basic_rows[:3]:
    print(f"  trade_date={r[1]} total_share={r[2]} total_mv={r[3]}")

# 直接用 fina_indicator 拿 EPS
fina_rows = tushare_call("fina_indicator", {"ts_code": ts},
                         "ts_code,end_date,eps,bps,roe")
print("\n=== FINA_INDICATOR EPS ===")
for r in fina_rows[:3]:
    print(f"  end_date={r[1]} eps={r[2]} bps={r[3]} roe={r[4]}")
