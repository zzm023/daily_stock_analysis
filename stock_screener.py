"""
全市场扫描器 v7.1
每周一从 CSI 300 + CSI 500 中按六类框架筛选候选 → PushPlus
- daily_basic 用全市场单日查询（不支持 ts_code 批量）
- fina_indicator 用 ts_code 批量（每批100个）
- 用 trade_cal 动态探测最近交易日
- 排除已在框架中的 52 只
- v7.1：排除保险股（PE假便宜，需PEV估值，本扫描器不处理）

运行状态：✅ 已跑通（2026-08-12 命中10只）
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
    "中国太保", "中国平安", "新华保险", "中国人寿", "中国人保",
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
    print(f"[START] 全市场扫描 v7.1 {now:%Y-%m-%d}")

    latest_td = get_latest_trade_date(now)
    print(f"  [0] 最近交易日: {latest_td}")
    if not latest_td:
        push(f"🔍 框架扫描 {now:%m.%d}", "## 🔍 框架扫描失败\n\ntrade_cal 无法获取交易日。")
        return

    constituents = set()
    for idx in ["000300.SH", "000905.SH"]:
        fields, items = ts_df("index_weight", "index_code,con_code,trade_date",
                              index_code=idx)
        try:
            col = fields.index("con_code")
        except ValueError:
            col = 0
        for row in items:
            constituents.add(row[col].split(".")[0])

    print(f"  [1] 成分股总计: {len(constituents)} 只")

    fields, items = ts_df("stock_basic",
                          "ts_code,name,industry,list_date",
                          list_status="L")
    fc = {f: i for i, f in enumerate(fields)}
    stocks = {}
    for row in items:
        code = row[fc["ts_code"]].split(".")[0]
        if constituents and code not in constituents:
            continue
        ld = row[fc["list_date"]] if fc.get("list_date") is not None else ""
        if ld and ld > "20230701":
            continue
        stocks[code] = {"name": row[fc["name"]], "industry": row[fc["industry"]]}

    print(f"  [2] 有效标的: {len(stocks)} 只")
    if len(stocks) == 0:
        push(f"🔍 框架扫描 {now:%m.%d}", "## 🔍 框架扫描失败\n\n基础信息无数据。")
        return

    print(f"  拉取 daily_basic 全市场 @ {latest_td} ...")
    all_items = []
    offset = 0
    while True:
        f, it = ts_df("daily_basic", "ts_code,pe,pb,total_mv,dv_ratio",
                      trade_date=latest_td, limit=2000, offset=offset)
        if not it:
            break
        all_items.extend(it)
        if len(it) < 2000:
            break
        offset += 2000

    fc = {f: i for i, f in enumerate(f)}
    for row in all_items:
        code = row[fc["ts_code"]].split(".")[0]
        if code in stocks:
            stocks[code]["pe"] = row[fc["pe"]] if row[fc["pe"]] else None
            stocks[code]["pb"] = row[fc["pb"]] if row[fc["pb"]] else None
            stocks[code]["mv"] = row[fc["total_mv"]] if row[fc["total_mv"]] else None
            stocks[code]["dv"] = row[fc["dv_ratio"]] if row[fc["dv_ratio"]] else None
    print(f"  [3] 估值数据(全市场): {len(all_items)} 条")

    td_year = int(latest_td[:4])
    start_r = f"{td_year-3}0101"
    end_r = f"{td_year}1231"
    print(f"  拉取 fina_indicator @ {start_r}~{end_r} ...")
    code_list = list(stocks.keys())
    fields, items = ts_batch("fina_indicator", "ts_code,end_date,roe",
                             code_list, start_date=start_r, end_date=end_r)
    fc = {f: i for i, f in enumerate(fields)}
    roe_latest = {}
    for row in items:
        code = row[fc["ts_code"]].split(".")[0]
        ed = row[fc["end_date"]]
        if code not in stocks:
            continue
        if code not in roe_latest or ed > roe_latest[code][0]:
            roe_latest[code] = (ed, row[fc["roe"]])

    for code, (ed, roe) in roe_latest.items():
        try:
            stocks[code]["roe"] = float(roe)
        except:
            stocks[code]["roe"] = None
    print(f"  [4] ROE 覆盖: {len(roe_latest)} 只")

    # ── 5. 筛选 + 分类 ──
    results = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}
    for code, s in stocks.items():
        name = s["name"]
        if name in EXISTING:
            continue

        ind = s.get("industry", "")
        if ind == "保险":
            continue   # 保险股PE假便宜，需PEV估值，本扫描器不处理

        pe = s.get("pe")
        pb = s.get("pb")
        roe = s.get("roe")
        dv = s.get("dv")

        if pe is None or pe <= 0 or pe > 50:
            continue
        if pb is None or pb <= 0 or pb > 8:
            continue
        if roe is None or roe < 5:
            continue

        matched = False

        if ind in CAT_MAP[1] and dv and dv > 2.0 and pe < 20:
            results[1].append((name, code, pe, pb, roe, dv, ind))
            matched = True

        if dv and dv > 3.5 and pe < 15 and not matched:
            results[2].append((name, code, pe, pb, roe, dv, ind))
            matched = True

        if ind in CAT_MAP[4] and roe > 10 and pe < 25 and not matched:
            results[4].append((name, code, pe, pb, roe, dv, ind))
            matched = True

        if ind in CAT_MAP[5] and roe > 10 and pe < 30 and not matched:
            results[5].append((name, code, pe, pb, roe, dv, ind))
            matched = True

        if ind in CAT_MAP[6] and roe > 10 and pe < 30 and not matched:
            results[6].append((name, code, pe, pb, roe, dv, ind))
            matched = True

        if pb < 1.5 and roe > 0 and not matched:
            results[3].append((name, code, pe, pb, roe, dv, ind))

    total = sum(len(v) for v in results.values())
    cat_names = {1: "①永续债", 2: "②高息成长", 3: "③周期拐点",
                 4: "④全球寡头", 5: "⑤品牌心智", 6: "⑥小众冠军"}

    lines = [
        f"## 🔍 框架扫描 {now:%m.%d}",
        f"CSI300+CSI500 共{len(constituents)}只 → 命中 **{total}** 只",
        f"数据截至 {latest_td}",
        "",
    ]

    for cat_id in [1, 2, 3, 4, 5, 6]:
        if not results[cat_id]:
            continue
        lines.append(f"### {cat_names[cat_id]}（{len(results[cat_id])}只）")
        lines.append("")
        for name, code, pe, pb, roe, dv, ind in results[cat_id][:8]:
            parts = [f"- **{name}**({code})"]
            if pe: parts.append(f"PE{pe:.1f}")
            if pb: parts.append(f"PB{pb:.2f}")
            if roe: parts.append(f"ROE{roe:.1f}%")
            if dv: parts.append(f"息{dv:.1f}%")
            parts.append(f"| {ind}")
            lines.append(" ".join(parts))
        lines.append("")

    if total == 0:
        lines.append("无新候选。框架外无低估标的，现金为王。")

    lines.append("---")
    lines.append(f"自动扫描，仅筛选不荐买 | {now:%m-%d %H:%M}")

    push(f"🔍 框架扫描 {now:%m.%d}（{total}只）", "\n".join(lines))
    print(f"[DONE] 命中 {total} 只")


if __name__ == "__main__":
    main()
