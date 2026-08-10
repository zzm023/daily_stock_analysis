"""
行业集中度监控 v4
大分类：金融/消费/制造/科技/资源/基建/其他
持仓市值 + 框架覆盖 → 分散度一目了然
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

# 大分类
BIG_SECTOR = {
    # 金融
    "600036": "金融", "601601": "金融",
    # 资源
    "600188": "资源", "000792": "资源", "002601": "资源", "600299": "资源",
    "603806": "资源", "601058": "资源",
    # 基建/公用
    "600018": "基建公用", "601816": "基建公用", "600900": "基建公用",
    "600941": "基建公用", "600585": "基建公用", "000429": "基建公用",
    "603568": "基建公用", "600007": "基建公用",
    # 制造
    "000157": "制造", "600031": "制造", "600660": "制造",
    "600761": "制造", "600309": "制造", "002508": "制造",
    "002032": "制造", "002884": "制造", "002318": "制造",
    "603855": "制造", "603508": "制造", "000651": "制造",
    "600066": "制造", "000333": "制造", "600690": "制造",
    "000708": "制造",
    # 科技
    "600406": "科技", "688187": "科技", "300124": "科技",
    "002410": "科技", "300627": "科技", "002837": "科技",
    "300628": "科技", "300832": "科技", "600845": "科技",
    "002747": "科技",
    # 消费
    "600598": "消费", "300498": "消费", "000538": "消费",
    "603605": "消费", "605098": "消费", "600298": "消费",
    "603288": "消费", "002027": "消费",
    # 医药
    "600161": "医药", "600486": "医药",
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
    print(f"[START] 行业集中度 v4 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    # 所有代码
    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    fw_codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    all_codes = list(set(hold_codes + fw_codes))
    prices = batch_prices(all_codes)

    cash = hold.get("cash", 0)

    # ── 以大类聚合：持仓市值 + 框架股列表 ──
    sec_hold_mv = {}
    sec_hold_detail = {}
    sec_fw = {}

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue
        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        price = prices.get(code, 0)
        mv = price * shares if price else cost * shares
        sec = BIG_SECTOR.get(code, "其他")
        sec_hold_mv[sec] = sec_hold_mv.get(sec, 0) + mv
        pnl = (price - cost) / cost * 100 if cost > 0 and price else 0
        sec_hold_detail.setdefault(sec, []).append(f"{name} {mv:,.0f} {pnl:+.0f}%")

    for code, t in trigger.items():
        if not isinstance(t, dict):
            continue
        sec = BIG_SECTOR.get(code, "其他")
        sec_fw.setdefault(sec, []).append(t.get("name", code))

    total_mv = sum(sec_hold_mv.values())
    total_asset = total_mv + cash

    lines = [f"## 行业集中度 - {now:%m.%d}", "",
             f"总市值 {total_mv:,.0f} + 现金 {cash:,.0f} = {total_asset:,.0f} | 现金 {cash/total_asset*100:.0f}%", ""]

    # 按持仓市值排序
    for sec in sorted(sec_hold_mv, key=sec_hold_mv.get, reverse=True):
        mv = sec_hold_mv[sec]
        pct = mv / total_mv * 100
        bar = "#" * int(pct / 5) + "-" * (20 - int(pct / 5))
        warning = " !!超标" if pct > WARN else ""

        fw_list = sec_fw.get(sec, [])
        fw_str = f"框架{len(fw_list)}只" if fw_list else ""

        lines.append(f"**{sec}** {pct:.0f}% {bar} {warning}")
        lines.append(f"> 持仓: {mv:,.0f} | {fw_str}")
        if sec in sec_hold_detail:
            for d in sec_hold_detail[sec]:
                lines.append(f"  - {d}")

        # 列出框架股（未持有）
        held_names = {v.get("name", "") for v in hold.values() if isinstance(v, dict)}
        fw_unheld = [n for n in fw_list if n not in held_names]
        if fw_unheld and len(fw_unheld) <= 20:
            lines.append(f"  可选: {' / '.join(fw_unheld)}")
        elif fw_unheld:
            lines.append(f"  可选: {' / '.join(fw_unheld[:15])} ...等{len(fw_unheld)}只")
        lines.append("")

    # 空大类（无持仓但有框架股）
    for sec, fw_list in sorted(sec_fw.items(), key=lambda x: len(x[1]), reverse=True):
        if sec in sec_hold_mv:
            continue
        held_names = {v.get("name", "") for v in hold.values() if isinstance(v, dict)}
        fw_unheld = [n for n in fw_list if n not in held_names]
        if fw_unheld:
            lines.append(f"**{sec}** 无持仓 | 框架{len(fw_list)}只")
            if len(fw_unheld) <= 15:
                lines.append(f"  可选: {' / '.join(fw_unheld)}")
            else:
                lines.append(f"  可选: {' / '.join(fw_unheld[:12])} ...等{len(fw_unheld)}只")
            lines.append("")

    # 告警
    over = [(s, sec_hold_mv[s]/total_mv*100) for s in sec_hold_mv if sec_hold_mv[s]/total_mv*100 > WARN]
    if over:
        lines.append(f"> {WARN}%超标: " + ", ".join(f"{s}{p:.0f}%" for s, p in over))

    push(f"行业集中度 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(sec_hold_mv)}类有持仓")


if __name__ == "__main__":
    main()
