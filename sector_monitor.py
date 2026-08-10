"""
行业集中度监控 v7
每个未持仓行业一行 → 每只股票单独一行
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
    "600036": "银行", "601601": "保险",
    "600188": "煤炭",
    "000792": "化工", "002601": "化工", "600299": "化工",
    "600309": "化工", "600486": "化工", "603806": "化工",
    "600900": "电力", "603568": "环保",
    "600018": "交通运输", "601816": "交通运输", "000429": "交通运输",
    "600941": "通信", "300628": "通信", "300627": "通信",
    "600007": "房地产",
    "000157": "工程机械", "600031": "工程机械", "600761": "工程机械",
    "002884": "通用设备", "002837": "通用设备", "002318": "钢铁",
    "000708": "钢铁",
    "600660": "汽车", "601058": "汽车", "600066": "汽车",
    "002508": "家电", "002032": "家电", "000651": "家电",
    "000333": "家电", "600690": "家电",
    "600406": "电力设备", "603855": "电力设备",
    "603508": "铁路设备",
    "600585": "建材",
    "688187": "半导体", "300124": "工控自动化",
    "002747": "工控自动化",
    "002410": "软件", "600845": "软件",
    "300832": "医疗器械",
    "600598": "农业", "300498": "农业",
    "000538": "医药", "600161": "医药",
    "603605": "化妆品", "605098": "教育",
    "600298": "食品饮料", "603288": "食品饮料",
    "002027": "传媒",
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
    print(f"[START] 行业集中度 v7 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    fw_codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    all_codes = list(set(hold_codes + fw_codes))
    prices = batch_prices(all_codes)
    cash = hold.get("cash", 0)

    sec_mv = {}
    sec_held = {}
    sec_fw = {}

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        price = prices.get(code, 0)
        mv = price * shares if price else cost * shares
        sec = SECTOR.get(code, "其他")
        sec_mv[sec] = sec_mv.get(sec, 0) + mv
        pnl = (price - cost) / cost * 100 if cost > 0 and price else 0
        sec_held.setdefault(sec, []).append((name, mv, pnl))

    for code, t in trigger.items():
        if not isinstance(t, dict):
            continue
        sec = SECTOR.get(code, "其他")
        sec_fw.setdefault(sec, []).append(t.get("name", code))

    total_mv = sum(sec_mv.values())
    total_asset = total_mv + cash

    lines = [f"# 行业集中度 {now:%m}.{now:%d}",
             f"总 {total_asset/10000:.0f}万 | 仓{total_mv/10000:.0f} + 现{cash/10000:.0f}万 ({cash/total_asset*100:.0f}%)",
             ""]

    lines.append("## 持仓")
    for sec in sorted(sec_mv, key=sec_mv.get, reverse=True):
        mv = sec_mv[sec]
        pct = mv / total_mv * 100
        flag = " ⚠️" if pct > WARN else ""
        lines.append(f"**{sec}{flag}** {pct:.0f}% {mv/10000:.1f}万")
        for name, m, pnl in sec_held.get(sec, []):
            lines.append(f"　{m/10000:.1f}万 {name} {pnl:+.0f}%")
    lines.append("")

    lines.append("## 未持仓")
    held_names = {v.get("name", "") for v in hold.values() if isinstance(v, dict)}
    for sec, fws in sorted(sec_fw.items(), key=lambda x: -len(x[1])):
        if sec in sec_mv:
            continue
        unheld = [n for n in fws if n not in held_names]
        if not unheld:
            continue
        lines.append(f"**{sec}**")
        for n in unheld:
            lines.append(f"　{n}")
        lines.append("")

    lines.append(f"> 行业>{WARN}%告警")

    push(f"行业集中度 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
