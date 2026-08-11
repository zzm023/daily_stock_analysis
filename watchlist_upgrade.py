"""
观察清单升级 v1
战略→战术 三灯全亮自动升
"""
import os
import json
import requests
import re
import math
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

THRESHOLDS = {
    "pe_pct": 0.30,       # PE 分位 < 30%
    "pb_pct": 0.30,       # PB 分位 < 30%
    "profit_min": -10.0,  # 利润增速 > -10%
    "drawdown": 0.20,     # 距 52 周高点 > 20%
}

GROWTH = {
    "600036": 1.2, "601601": 64.9, "600031": 27.4,
    "600585": -26.0, "600188": 8.5, "600660": 25.0,
    "600941": 5.2, "000333": 14.3, "688187": 24.8,
    "603288": -18.0, "600900": 7.3, "000651": 10.2,
    "600845": -3.5, "002027": 18.0, "000708": 8.2,
    "002601": 45.0, "600161": 46.5, "300498": 110.0,
    "600690": 12.8, "000157": 41.5, "002747": -20.0,
    "300124": -10.0, "605117": 15.0, "603298": 5.0,
    "603699": 8.0, "002508": 3.0, "002372": 5.0,
    "300627": 12.0, "600299": 25.0, "600486": -5.0,
    "688036": 10.0, "601058": 30.0, "600309": -8.0,
    "000792": -40.0, "603806": -15.0, "600298": -8.0,
    "601816": 3.0, "002475": 20.0, "600066": 15.0,
}


def batch_detail(codes):
    """腾讯批量 → 价格+PE+PB+52周高低"""
    results = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i + 30]
        symbols = ",".join(
            f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch
        )
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 48:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    pb = float(parts[46]) if parts[46] and parts[46] != "-" else None
                    high52 = float(parts[33]) if parts[33] else None
                    low52 = float(parts[34]) if parts[34] else None
                    if price:
                        results[c] = {
                            "price": price, "pe": pe, "pb": pb,
                            "high52": high52, "low52": low52,
                        }
                except Exception:
                    pass
        except Exception:
            pass
    return results


def get_hist_pe_pb(code):
    """估算 PE/PB 分位（取框架分位数据或兜底）"""
    # 从 framework_state 里读已有分位
    try:
        state = json.load(open(STATE_FILE, "r", encoding="utf-8"))
        t = state.get("trigger", {}).get(code)
        if isinstance(t, dict):
            pe_pct = t.get("pe_percentile")
            pb_pct = t.get("pb_percentile")
            if pe_pct is not None and pb_pct is not None:
                return pe_pct / 100, pb_pct / 100
    except Exception:
        pass
    return None, None


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        requests.post(
            "http://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown",
                "topic": PUSHPLUS_TOPIC,
            },
            timeout=10
        )
    except Exception:
        pass


def main():
    now = datetime.now()
    print(f"[START] 观察清单升级 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    # 找所有 ⑥战略观察
    strategic = []
    for code in trigger:
        if not isinstance(trigger.get(code), dict):
            continue
        tag = trigger[code].get("tag", "")
        if "⑥" in tag:
            strategic.append(code)

    if not strategic:
        print("  无战略观察股")
        return

    print(f"  战略观察 {len(strategic)} 只")

    quotes = batch_detail(strategic)

    promoted = []
    near = []

    for code in strategic:
        t = trigger[code]
        name = t.get("name", code)

        q = quotes.get(code, {})
        if not q or not q.get("price"):
            continue

        price = q["price"]
        pe = q.get("pe")
        pb = q.get("pb")
        high52 = q.get("high52")

        # 灯1: 估值分位
        pe_pct, pb_pct = get_hist_pe_pb(code)
        val_ok = False
        val_detail = ""
        if pe_pct is not None and pe_pct < THRESHOLDS["pe_pct"]:
            val_ok = True
            val_detail = f"PE分位{pe_pct:.0%}"
        elif pb_pct is not None and pb_pct < THRESHOLDS["pb_pct"]:
            val_ok = True
            val_detail = f"PB分位{pb_pct:.0%}"

        # 灯2: 基本面
        g = GROWTH.get(code)
        fund_ok = g is not None and g > THRESHOLDS["profit_min"]

        # 灯3: 回调
        dd_ok = False
        dd_pct = 0
        if high52 and high52 > 0:
            dd_pct = (high52 - price) / high52
            dd_ok = dd_pct > THRESHOLDS["drawdown"]

        lights = sum([val_ok, fund_ok, dd_ok])
        details = {
            "name": name, "code": code, "price": price,
            "pe": pe, "pb": pb,
            "val_ok": val_ok, "val_detail": val_detail,
            "fund_ok": fund_ok, "profit": g,
            "dd_ok": dd_ok, "dd_pct": dd_pct,
            "high52": high52,
            "lights": lights,
        }

        if lights >= 3:
            promoted.append(details)
        elif lights >= 2:
            near.append(details)

    # 输出
    lines = [
        f"观察清单升级 {now:%m}.{now:%d}",
        f"三灯: 估值低 | 基本面OK | 回调深",
    ]

    if promoted:
        lines.append("")
        lines.append(f"🚀 建议升级 ⑥→⑦（{len(promoted)}只）")
        for d in promoted:
            lines.append(f"- {d['name']} {d['price']:.2f}")
            lights_str = []
            if d["val_ok"]: lights_str.append(d["val_detail"])
            if d["fund_ok"]: lights_str.append(f"利润{d['profit']:+.0f}%")
            if d["dd_ok"]: lights_str.append(f"距高点{d['dd_pct']:.0%}")
            lines.append(f"  {' | '.join(lights_str)}")
            lines.append(f"  → 请手动设置触发价，加入⑦战术观察")

    if near:
        lines.append("")
        lines.append(f"🟡 接近（2灯，{len(near)}只）")
        for d in near:
            missing = []
            if not d["val_ok"]: missing.append("估值")
            if not d["fund_ok"]: missing.append("基本面")
            if not d["dd_ok"]: missing.append("回调")
            lines.append(f"- {d['name']} 缺{'/'.join(missing)}")

    if not promoted and not near:
        lines.append("")
        lines.append("无符合条件的升级")

    lines.append("")
    lines.append("> 三灯全亮→手动升级 | 每周一")

    if promoted or near:
        push(f"观察升级 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 升级{len(promoted)}只 接近{len(near)}只")


if __name__ == "__main__":
    main()
