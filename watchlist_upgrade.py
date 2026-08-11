"""
观察清单 v2
pe_upper/pb_lower 自动分类 + 三灯升级
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
    "600018": 5.0, "600598": 8.0, "603568": 10.0,
    "600007": 8.0, "000429": 6.0, "600761": 15.0,
    "000538": 5.0, "603605": 15.0, "605098": 10.0,
    "300628": 8.0, "002032": 12.0, "002884": 10.0,
    "002318": 15.0, "603855": 10.0, "603508": 12.0,
    "300832": 12.0, "002837": 20.0, "002410": -5.0,
    "600406": 10.0,
}


def classify_stock(t):
    """自动分类 ⑥/⑦/⑧"""
    trigger_price = t.get("trigger_price", 0)
    pe_upper = t.get("pe_upper", 20)
    pb_lower = t.get("pb_lower", 2)

    # ⑧: 无触发价 = 清除/观察，不在本系统内
    if trigger_price <= 0:
        return "⑧清除"

    # ⑥: PE上限高(>25)或PB下限高(>4) → 偏成长/科技，需观察
    if pe_upper > 25 or pb_lower > 4:
        return "⑥战略观察"

    # ⑦: 有触发价且估值合理 → 战术观察，等击球
    return "⑦战术观察"


def batch_detail(codes):
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
                    if price:
                        results[c] = {
                            "price": price, "pe": pe, "pb": pb, "high52": high52,
                        }
                except Exception:
                    pass
        except Exception:
            pass
    return results


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
    print(f"[START] 观察清单 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})

    # 自动分类
    strategic = []
    tactical = []
    cleared = []
    for code in trigger:
        if not isinstance(trigger[code], dict):
            continue
        t = trigger[code]
        tag = t.get("tag") or classify_stock(t)
        t["tag"] = tag  # 写回
        if "⑥" in tag:
            strategic.append(code)
        elif "⑧" in tag:
            cleared.append(code)
        else:
            tactical.append(code)

    print(f"  ⑥战略 {len(strategic)} | ⑦战术 {len(tactical)} | ⑧清除 {len(cleared)}")

    # 保存分类
    state["trigger"] = trigger
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    if not strategic:
        print("  无⑥战略观察股")
        return

    quotes = batch_detail(strategic)
    promoted = []
    near = []

    for code in strategic:
        t = trigger[code]
        name = t.get("name", code)
        pe_upper = t.get("pe_upper", 20)

        q = quotes.get(code, {})
        if not q:
            continue

        price = q["price"]
        pe = q.get("pe")
        high52 = q.get("high52")

        # 灯1: PE < pe_upper × 0.8（跌入合理区）
        val_ok = pe is not None and pe < pe_upper * 0.8

        # 灯2: 基本面
        g = GROWTH.get(code)
        fund_ok = g is not None and g > -10

        # 灯3: 回调
        dd_ok = False
        dd_pct = 0
        if high52 and high52 > 0:
            dd_pct = (high52 - price) / high52
            dd_ok = dd_pct > 0.20

        lights = sum([val_ok, fund_ok, dd_ok])

        d = {
            "name": name, "code": code, "price": price, "pe": pe,
            "pe_upper": pe_upper, "val_ok": val_ok,
            "fund_ok": fund_ok, "profit": g,
            "dd_ok": dd_ok, "dd_pct": dd_pct,
            "lights": lights,
        }

        if lights >= 3:
            promoted.append(d)
        elif lights >= 2:
            near.append(d)

    lines = [
        f"观察升级 {now:%m}.{now:%d}",
        f"⑥战略{len(strategic)}只 | 三灯: PE回落 | 利润OK | 回调深",
    ]

    if promoted:
        lines.append("")
        lines.append(f"🚀 建议升级 ⑥→⑦（{len(promoted)}只）")
        for d in promoted:
            lines.append(f"- {d['name']} PE{d['pe']:.0f}/{d['pe_upper']} {d['price']:.2f}")
            ls = []
            if d["val_ok"]: ls.append("PE回落")
            if d["fund_ok"]: ls.append(f"利润{d['profit']:+.0f}%")
            if d["dd_ok"]: ls.append(f"跌{d['dd_pct']:.0%}")
            lines.append(f"  {' | '.join(ls)}")
            lines.append(f"  → 请在 framework_state.json 改 tag 为⑦，设置触发价")

    if near:
        lines.append("")
        lines.append(f"🟡 接近（2灯，{len(near)}只）")
        for d in near:
            miss = []
            if not d["val_ok"]: miss.append("PE仍高")
            if not d["fund_ok"]: miss.append("利润差")
            if not d["dd_ok"]: miss.append("回调不够")
            lines.append(f"- {d['name']} 缺{'/'.join(miss)}")

    if not promoted:
        lines.append("")
        lines.append("无三灯全亮  继续观察")

    lines.append("")
    lines.append("> 自动分类: pe_upper>25或pb_lower>4→⑥ | 每周一")

    push(f"观察升级 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 升级{len(promoted)}只")


if __name__ == "__main__":
    main()
