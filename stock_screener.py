"""
全市场扫描器 v2
每周一从 CSI 300 + CSI 500 中按六类框架筛选候选 → PushPlus
排除已在框架中的 52 只
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
    """返回 (fields, items)，带错误日志"""
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
    print(f"  [Tushare] {api_name} OK: {len(items)} 条")
    return d.get("fields", []), items


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 全市场扫描 v2 {now:%Y-%m-%d}")

    # ── 1. 成分股：按字段名定位 con_code 列 ──
    constituents = set()
    for idx in ["000300.SH", "000905.SH"]:
        print(f"  拉取 {idx} ...")
        fields, items = ts_df("index_weight", "index_code,con_code,trade_date",
                              index_code=idx)
        # 按字段名找 con_code 的列位置
        try:
            col = fields.index("con_code")
        except ValueError:
            col = 0
        for row in items:
            constituents.add(row[col].split(".")[0])
        print(f"    {idx}: {len(items)} 条")

    print(f"  [1] 成分股总计: {len(constituents)} 只")
    if len(constituents) < 50:
        print("  ⚠️ 成分股异常少，可能是 index_weight 权限不足或参数问题")
        # 兜底：直接取全部股票
        constituents = set()

    # ── 2. 基础信息 ──
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
        push(f"🔍 框架扫描 {now:%m.%d}", "## 🔍 框架扫描失败\n\n成分股或基础信息接口无数据，请检查 Tushare 积分/权限。")
        return

    codes = ",".join(stocks.keys())
    today = now.strftime("%Y%m%d")

    # ── 3. PE/PB ──
    fields, items = ts_df("daily_basic", "ts_code,pe,pb,total_mv",
                          ts_code=codes, trade_date=today)
    fc = {f: i for i, f in enumerate(fields)}
    for row in items:
        code = row[fc["ts_code"]].split(".")[0]
        if code in stocks:
            stocks[code]["pe"] = row[fc["pe"]] if row[fc["pe"]] else None
            stocks[code]["pb"] = row[fc["pb"]] if row[fc["pb"]] else None
            stocks[code]["mv"] = row[fc["total_mv"]] if row[fc["total_mv"]] else None
    print(f"  [3] 估值数据: {len(items)} 条")

    # ── 4. ROE（上年度） ──
    fy = str(int(now.strftime("%Y")) - 1)
    fields, items = ts_df("fina_indicator", "ts_code,roe",
                          ts_code=codes, end_date=f"{fy}1231")
    fc = {f: i for i, f in enumerate(fields)}
    for row in items:
        code = row[fc["ts_code"]].split(".")[0]
        if code in stocks:
            try:
                stocks[code]["roe"] = float(row[fc["roe"]])
            except:
                stocks[code]["roe"] = None
    print(f"  [4] ROE: {len(items)} 条")

    # ── 5. 股息率 ──
    fields, items = ts_df("daily_basic", "ts_code,dv_ratio",
                          ts_code=codes, trade_date=today)
    fc = {f: i for i, f in enumerate(fields)}
    for row in items:
        code = row[fc["ts_code"]].split(".")[0]
        if code in stocks:
            stocks[code]["dv"] = row[fc["dv_ratio"]] if row[fc["dv_ratio"]] else None
    print(f"  [5] 股息率: {len(items)} 条")

    # ── 6. 筛选 + 分类 ──
    results = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}
    for code, s in stocks.items():
        name = s["name"]
        if name in EXISTING:
            continue

        pe = s.get("pe")
        pb = s.get("pb")
        roe = s.get("roe")
        dv = s.get("dv")
        ind = s.get("industry", "")

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

    # ── 7. 推送 ──
    total = sum(len(v) for v in results.values())
    cat_names = {1: "①永续债", 2: "②高息成长", 3: "③周期拐点",
                 4: "④全球寡头", 5: "⑤品牌心智", 6: "⑥小众冠军"}

    lines = [
        f"## 🔍 框架扫描 {now:%m.%d}",
        f"CSI300+CSI500 共{len(constituents) if constituents else len(stocks)}只 → 命中 **{total}** 只",
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
