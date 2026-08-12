import os, requests

TOKEN = os.environ["TUSHARE_TOKEN"]

# 测试 income
r = requests.post("https://api.tushare.pro", json={
    "api_name": "income",
    "token": TOKEN,
    "params": {"ts_code": "600036.SH", "end_date": "20251231"},
    "fields": "ts_code,end_date,n_income_attr_p,total_revenue",
}, timeout=15)
print("=== income ===")
print(f"code: {r.json().get('code')}")
print(f"msg: {r.json().get('msg')}")
d = r.json().get("data")
if d:
    print(f"fields: {d.get('fields')}")
    print(f"items: {d.get('items')}")

# 测试 dividend
r2 = requests.post("https://api.tushare.pro", json={
    "api_name": "dividend",
    "token": TOKEN,
    "params": {"ts_code": "600036.SH"},
    "fields": "ts_code,cash_div,stk_div,end_date",
}, timeout=15)
print("=== dividend ===")
print(f"code: {r2.json().get('code')}")
print(f"msg: {r2.json().get('msg')}")
d2 = r2.json().get("data")
if d2:
    print(f"fields: {d2.get('fields')}")
    print(f"items: {d2.get('items')}")
