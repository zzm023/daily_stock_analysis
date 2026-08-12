"""
Tushare 连通测试 + 自动 IP 白名单
"""
import os, requests, json

TOKEN = os.environ["TUSHARE_TOKEN"]

# 1. 获取当前 IP
ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
print(f"当前IP: {ip}")

# 2. 更新白名单
r = requests.post(
    "https://api.tushare.pro",
    json={
        "api_name": "ip_whitelist",
        "token": TOKEN,
        "params": {"ip": ip},
    },
    timeout=10
)
result = r.json()
print(f"白名单更新: {result.get('msg', result)}")

# 3. 测试取数据
r2 = requests.post(
    "https://api.tushare.pro",
    json={
        "api_name": "daily",
        "token": TOKEN,
        "params": {"ts_code": "000001.SZ", "start_date": "20250808", "end_date": "20250808"},
        "fields": "ts_code,trade_date,close,pct_chg",
    },
    timeout=15
)
data = r2.json()
if data.get("code") == 0:
    rows = data["data"]
    print(f"✅ 连通成功！{len(rows)}行数据")
    for row in rows:
        print(f"  {row}")
else:
    print(f"❌ 失败: {data.get('msg')}")
