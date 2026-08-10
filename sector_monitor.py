"""
行业集中度监控 v3
修复：行业名简化 + 龙佰→钛白粉
"""
import os
import json
import requests
import re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

SECTOR = {
    "600036": "银行", "601601": "保险", "600018": "港口", "601816": "铁路",
    "600900": "水电", "600941": "电信", "600406": "电力设备",
    "600598": "农业", "603568": "环保", "600007": "商业地产",
    "000429": "高速", "000157": "工程机械", "600585": "水泥",
    "000792": "锂盐", "600188": "煤炭", "002601": "钛白粉",
    "600299": "氨基酸", "300498": "养殖", "000651": "家电",
    "600066": "客车", "000333": "家电", "600690": "家电",
    "600031": "工程机械", "600309": "MDI", "600660": "汽车玻璃",
    "600761": "叉车", "600486": "农药", "601058": "轮胎",
    "603806": "光伏材料", "000708": "特钢", "002027": "楼宇媒体",
    "000538": "中药", "603605": "化妆品", "605098": "管理培训",
    "600298": "酵母", "300628": "通信终端", "002508": "厨电",
    "002032": "炊具", "002884": "水泵", "002318": "钢管",
    "603855": "防爆电器", "603288": "调味品", "603508": "铁路信号",
    "600161": "血制品", "300832": "医疗器械", "688187": "轨交芯片",
    "300124": "工控", "002837": "温控", "300627": "导航",
    "002410": "建筑软件",
    # 持仓补充
    "600845": "工业软件", "002747": "机器人",
}
WARN = 30


def batch_prices(codes):
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            text = r.text
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", text)
                if m:
                    parts = m.group().split("~")
                    if len(parts) >= 4 and parts[3]:
                        prices[c] = float(parts[3])
        except:
            pass
    return prices


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 行业集中度 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(codes)
    cash = hold.get("cash", 0)

    sector_mv = {}
    sector_stocks = {}
    total_mv = 0

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        price = prices.get(code, 0)
        mv = price * shares if price else cost * shares
        total_mv += mv

        sec = SECTOR.get(code, "未分类")
        sector_mv[sec] = sector_mv.get(sec, 0) + mv
        sector_stocks.setdefault(sec, [])

        if cost < 0:
            sector_stocks[sec].append(f"  - {name} {mv:,.0f} | 零成本")
        elif price and cost:
            pnl = (price - cost) / cost * 100
            sector_stocks[sec].append(f"  - {name} {mv:,.0f} | {pnl:+.0f}%")
        else:
            sector_stocks[sec].append(f"  - {name} {mv:,.0f}")

    lines = [f"## 行业集中度 - {now:%m.%d}", "",
             f"总市值 {total_mv:,.0f} + 现金 {cash:,.0f} = {total_mv+cash:,.0f}", ""]

    for sec, mv in sorted(sector_mv.items(), key=lambda x: x[1], reverse=True):
        pct = mv / total_mv * 100
        bar = "#" * int(pct / 5) + "-" * (20 - int(pct / 5))
        flag = "!!" if pct > WARN else ""
        lines.append(f"{sec}: {pct:.0f}% {bar} {flag}")
        for s in sector_stocks[sec]:
            lines.append(s)
        lines.append("")

    # 告警
    over = [(s, p) for s, p in [(k, sector_mv[k]/total_mv*100) for k in sector_mv] if p > WARN]
    if over:
        lines.append(f"> {WARN}% 以上: " + ", ".join(f"{s}{p:.0f}%" for s, p in over))

    push(f"行业集中度 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(sector_mv)}行业 {len(prices)}/{len(codes)}价")


if __name__ == "__main__":
    main()
