"""
行业集中度监控 v1
持仓按行业分组，单一行业 >30% 告警
框架股行业分布一览
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 框架股 → 行业
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
}

CONCENTRATION_WARNING = 30
CONCENTRATION_DANGER = 40


def batch_prices(codes):
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for line in r.text.strip().split("\n"):
                if "=" not in line or '""' in line:
                    continue
                code = line.split("_")[-1].split("=")[0].replace("sh","").replace("sz","")
                parts = line.split("~")
                if len(parts) >= 4 and parts[3]:
                    prices[code] = float(parts[3])
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
    print(f"[START] 行业集中度 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    # 批量取持有价
    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(hold_codes)

    # ── 持仓行业分组 ──
    sector_hold = {}  # 行业 → {总市值, 股票列表}
    total_mv = 0

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        price = prices.get(code, 0)

        mv = price * shares if price else cost * shares
        total_mv += mv if mv > 0 else 0

        sector = SECTOR.get(code, "其他")
        if sector not in sector_hold:
            sector_hold[sector] = {"mv": 0, "stocks": []}
        sector_hold[sector]["mv"] += mv
        sector_hold[sector]["stocks"].append((name, mv, cost, price, shares))

    cash = hold.get("cash", 0)
    total_asset = total_mv + cash

    # ── 框架股行业分布 ──
    sector_fw = {}
    for code, sector in SECTOR.items():
        sector_fw.setdefault(sector, []).append(code)

    # ── 检查告警 ──
    warnings = []
    for sector, data in sector_hold.items():
        pct = data["mv"] / total_mv * 100 if total_mv else 0
        if pct >= CONCENTRATION_DANGER:
            warnings.append(f"🔴 {sector} {pct:.0f}% — 严重超标 >{CONCENTRATION_DANGER}%")
        elif pct >= CONCENTRATION_WARNING:
            warnings.append(f"🟡 {sector} {pct:.0f}% — 超标 >{CONCENTRATION_WARNING}%")

    # ── 推送 ──
    lines = [f"## 🏭 行业集中度 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 总市值{total_mv:,.0f}", ""]

    # 持仓行业
    lines.append("### 💼 持仓行业分布")
    lines.append("")
    for sector, data in sorted(sector_hold.items(), key=lambda x: x[1]["mv"], reverse=True):
        pct = data["mv"] / total_mv * 100 if total_mv else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"**{sector}** {pct:.1f}% {bar}")
        for name, mv, cost, price, shares in data["stocks"]:
            if cost and cost > 0 and price:
                pnl = (price - cost) / cost * 100
                lines.append(f"  └ {name} 市值{mv:,.0f} | {pnl:+.0f}%")
            elif cost < 0:
                lines.append(f"  └ {name} 市值{mv:,.0f} | 零成本")
        lines.append("")

    if warnings:
        lines.append("### ⚠️ 集中度告警")
        for w in warnings:
            lines.append(w)
        lines.append("")

    # 框架行业分布
    lines.append("### 📊 框架股行业分布")
    lines.append("")
    for sector, codes in sorted(sector_fw.items(), key=lambda x: len(x[1]), reverse=True):
        lines.append(f"- **{sector}**：{len(codes)}只")

    lines.append("")
    lines.append("---")
    lines.append(f"📌 单一行业 >{CONCENTRATION_WARNING}% 即告警。分散=保护本金。")

    push(f"🏭 行业集中度 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {'有告警' if warnings else '无告警'}")


if __name__ == "__main__":
    main()
