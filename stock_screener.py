"""
全市场扫描器 v6 - 诊断版
定位 daily_basic 返回 0 条的原因
"""

import os, json, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")

EXISTING = {
    "长江电力", "中国神华", "中国海油", "中国移动", "中国石油",
    "招商银行", "建设银行", "工商银行", "农业银行", "交通银行", "中国银行",
    "格力电器", "美的集团", "海尔智家",
    "伊利股份", "双汇发展", "海天味业", "贵州茅台", "五粮液", "泸州老窖",
    "云南白药", "片仔癀", "同仁堂", "珀莱雅",
    "分众传媒", "苏泊尔",
    "万华化学", "宝钢股份", "中信特钢", "龙佰集团",
    "温氏股份", "牧原股份", "北大荒",
    "中联重科", "安徽合力",
    "中国太保", "中国平安",
    "京沪高铁", "上港集团", "中国国贸", "宁沪高速",
    "伟明环保", "凌霄泵业", "华荣股份", "思维列控",
    "国电南瑞", "宝信软件", "时代电气", "华测导航",
    "扬农化工", "安迪苏", "天坛生物",
}

CAT_MAP = {
    1: {
        "水力发电", "火力发电", "核力发电", "风力发电", "光伏发电",
        "高速公路", "铁路运输", "港口", "机场", "水务", "燃气",
        "黄金", "铜", "稀土",
    },
    4: {
        "工程机械", "电池", "光伏设备", "消费电子", "家电",
        "化学制品", "农化制品", "化学纤维",
    },
    5: {
        "白酒", "啤酒", "乳品", "调味发酵品", "食品加工",
        "中药", "化学制药", "医美", "化妆品", "个护用品",
        "家居用品", "小家电", "厨房电器",
        "运动服装", "旅游零售",
    },
    6: {
        "仪器仪表", "自动化设备", "专用设备", "通用设备",
        "航空装备", "军工电子", "通信设备", "半导体",
        "汽车零部件", "摩托车", "金属制品", "塑料",
    },
}


def to_ts_code(code):
    if code.startswith("6"):
        return code + ".SH"
    elif code.startswith(("0", "3")):
        return code + ".SZ"
    elif code.startswith(("8", "4")):
        return code + ".BJ"
    return code


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        r = requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title,
            "content": content, "template": "markdown",
            "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
        print(f"  [Push] {'OK' if r.json().get('code') == 200 else r.json()}")
    except Exception as e:
        print(f"  [Push] {e}")


def ts_raw(api_name, fields, **params):
    """返回原始 json，不解析，用于诊断"""
    r = requests.post("http://api.tushare.pro", json={
        "api_name": api_name, "token": TUSHARE_TOKEN,
        "params": {**params, "fields": fields},
    }, timeout=30)
    return r.json()


def ts_df(api_name, fields, **params):
    r = requests.post("http://api.tushare.pro", json={
        "api_name": api_name, "token": TUSHARE_TOKEN,
        "params": {**params, "fields": fields},
    }, timeout=30)
    data = r.json()
    code = data.get("code")
    if code != 0:
        print(f"  [Tushare] {api_name} 错误({code}): {data.get('msg')}")
        return [], []
    d = data.get("data", {})
    items = d.get("items", [])
    return d.get("fields", []), items


def ts_batch(api_name, fields, codes, **params):
    all_fields = None
    all_items = []
    for i in range(0, len(codes), 100):
        batch = [to_ts_code(c) for c in codes[i:i+100]]
        f, it = ts_df(api_name, fields, ts_code=",".join(batch), **params)
        all_fields = f
        all_items.extend(it)
    return all_fields, all_items


def get_latest_trade_date(now):
    end = now.strftime("%Y%m%d")
    start = (now - timedelta(days=1100)).strftime("%Y%m%d")
    fields, items = ts_df("trade_cal", "cal_date,is_open", exchange="SSE",
                          start_date=start, end_date=end)
    if not fields:
        return None
    fc = {f: i for i, f in enumerate(fields)}
    open_days = []
    for row in items:
        if row[fc["is_open"]] == 1:
            open_days.append(row[fc["cal_date"]])
    open_days.sort()
    return open_days[-1] if open_days else None


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 全市场扫描 v6 诊断 {now:%Y-%m-%d}")

    latest_td = get_latest_trade_date(now)
    print(f"  [0] 最近交易日: {latest_td}")

    # ===== 诊断开始 =====
    print("=== 诊断 ===")
    # 1. 单股 + 无 dv_ratio + trade_date
    d1 = ts_raw("daily_basic", "ts_code,pe,pb,total_mv",
                ts_code="000001.SZ", trade_date=latest_td)
    print(f"  测1 [无dv_ratio+trade_date]: code={d1.get('code')}, "
          f"条数={len(d1.get('data',{}).get('items',[]))}, msg={d1.get('msg')}")

    # 2. 单股 + 有 dv_ratio + trade_date
    d2 = ts_raw("daily_basic", "ts_code,pe,pb,total_mv,dv_ratio",
                ts_code="000001.SZ", trade_date=latest_td)
    print(f"  测2 [有dv_ratio+trade_date]: code={d2.get('code')}, "
          f"条数={len(d2.get('data',{}).get('items',[]))}, msg={d2.get('msg')}")

    # 3. 单股 + 无 dv_ratio + 日期范围
    d3 = ts_raw("daily_basic", "ts_code,pe,pb,total_mv",
                ts_code="000001.SZ",
                start_date=(now - timedelta(days=15)).strftime("%Y%m%d"),
                end_date=latest_td)
    print(f"  测3 [无dv_ratio+日期范围]: code={d3.get('code')}, "
          f"条数={len(d3.get('data',{}).get('items',[]))}, msg={d3.get('msg')}")

    # 4. 单股 + 无 dv_ratio + 前一天
    d4 = ts_raw("daily_basic", "ts_code,pe,pb,total_mv",
                ts_code="000001.SZ", trade_date="20260811")
    print(f"  测4 [无dv_ratio+0811]: code={d4.get('code')}, "
          f"条数={len(d4.get('data',{}).get('items',[]))}, msg={d4.get('msg')}")

    # 5. 单股 + 无 dv_ratio + 不传日期
    d5 = ts_raw("daily_basic", "ts_code,pe,pb,total_mv",
                ts_code="000001.SZ")
    print(f"  测5 [无dv_ratio+无日期]: code={d5.get('code')}, "
          f"条数={len(d5.get('data',{}).get('items',[]))}, msg={d5.get('msg')}")
    print("=== 诊断结束 ===")

    # 诊断后先退出，不发推送
    print("[DONE] 诊断完成，请把以上日志发我")
    return


if __name__ == "__main__":
    main()
