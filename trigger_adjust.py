"""
触发价动态调整 v3
核心规则：PE锚触发价 与 PB锚触发价 取较高者
保底不低过原触发价50%，封顶不超现价
PE > 3x锚 → 标记"利润冰点，用PB锚"
"""
import os
import json
import requests
from datetime import datetime, date
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

FRAMEWORK = {
    "600036": (8, 1.0), "601601": (8, 1.0),
    "600018": (15, 0.9), "601816": (20, 1.0),
    "600900": (18, 2.0), "600941": (12, 1.0),
    "600406": (20, 2.0), "600598": (20, 2.5),
    "603568": (20, 3.0), "600007": (18, 1.5),
    "000429": (12, 1.2), "000157": (15, 1.5),
    "600585": (15, 0.8), "000792": (30, 2.0),
    "600188": (8, 1.0), "002601": (18, 2.0),
    "600299": (20, 1.5), "300498": (15, 1.5),
    "000651": (10, 1.5), "600066": (12, 1.5),
    "000333": (12, 2.0), "600690": (13, 1.8),
    "600031": (12, 1.5), "600309": (18, 2.5),
    "600660": (15, 2.0), "600761": (12, 1.5),
    "600486": (18, 2.0), "601058": (15, 1.5),
    "603806": (20, 2.5), "000708": (14, 1.8),
    "002027": (14, 3.0), "000538": (20, 2.0),
    "603605": (25, 5.0), "605098": (18, 3.0),
    "600298": (22, 2.5), "300628": (18, 3.0),
    "002508": (15, 2.0), "002032": (18, 3.0),
    "002884": (15, 1.5), "002318": (15, 2.0),
    "603855": (16, 2.0), "603288": (35, 5.0),
    "603508": (15, 1.5), "600161": (19, 3.0),
    "300832": (30, 4.0), "688187": (25, 2.5),
    "300124": (30, 4.0), "002837": (30, 4.0),
    "300627": (30, 4.0), "002410": (40, 4.0),
}


def batch_get_data(codes):
    """批量取价+PE+PB"""
    result = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i+30]
        symbols = ",".join(
            f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch
        )
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for line in r.text.strip().split("\n"):
                if "=" not in line or '""' in line:
                    continue
                code = line.split("_")[-1].split("=")[0]
                code = code.replace("sh","").replace("sz","")
                parts = line.split("~")
                if len(parts) < 45:
                    continue
                price = float(parts[3]) if parts[3] else 0
                pe = float(parts[39]) if parts[39] and parts[39] != "0.00" else 0
                pb = float(parts[43]) if parts[43] and parts[43] != "0.00" else 0
                result[code] = (price, pe, pb)
        except Exception as e:
            print(f"  批量失败: {e}")
    return result


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
    print(f"[START] 触发价动态调整 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})

    codes = list(FRAMEWORK.keys())
    print(f"  批量取价 {len(codes)} 只 ...")
    data = batch_get_data(codes)
    print(f"  获取到 {len(data)} 只")

    adjustments = []

    for code, (anchor_pe, anchor_pb) in FRAMEWORK.items():
        t = trigger.get(code)
        if not t or not isinstance(t, dict):
            continue

        name = t.get("name", code)
        old_trigger = t.get("trigger_price", 0)
        if not old_trigger:
            continue

        d = data.get(code)
        if not d:
            continue
        price, pe_now, pb_now = d
        if not price or not pe_now or not pb_now:
            continue

        # ── 计算两个锚的触发价 ──
        # PE锚触发价 = 锚PE × (现价/当前PE) = 锚PE × EPS
        trigger_pe = round(anchor_pe * price / pe_now, 2)

        # PB锚触发价 = 锚PB × (现价/当前PB) = 锚PB × BVPS
        trigger_pb = round(anchor_pb * price / pb_now, 2)

        # 取较高者（保守：不压得太低）
        suggested_raw = max(trigger_pe, trigger_pb)

        # 保底/封顶
        floor = old_trigger * 0.5   # 不低于旧触发50%
        ceiling = price              # 不高于现价
        suggested = max(min(suggested_raw, ceiling), floor)

        # 标记
        notes = []
        if pe_now > anchor_pe * 3:
            notes.append("利润冰点")
        if suggested_raw < floor:
            notes.append(f"保底{floor:.2f}")
        if suggested_raw > ceiling:
            notes.append("高于现价")

        change_pct = round((suggested - old_trigger) / old_trigger * 100, 1)

        if abs(change_pct) >= 10:
            adjustments.append({
                "code": code, "name": name, "old": old_trigger,
                "new": suggested, "chg": change_pct,
                "price": price, "pe_now": pe_now, "anchor_pe": anchor_pe,
                "pb_now": pb_now, "anchor_pb": anchor_pb,
                "notes": notes,
            })

    if not adjustments:
        lines = ["## 🔧 触发价动态调整 — 无需调整", "",
                 "✅ 所有触发价合理，变动<10%。"]
        push(f"🔧 触发价调整 {now:%Y.%m.%d}", "\n".join(lines))
        print("[DONE] 无需调整")
        return

    adjustments.sort(key=lambda x: abs(x["chg"]), reverse=True)
    up = [a for a in adjustments if a["chg"] > 0]
    down = [a for a in adjustments if a["chg"] < 0]

    lines = [f"## 🔧 触发价调整建议 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | ⬆️上调{len(up)}只 ⬇️下调{len(down)}只",
             "",
             "> 规则：PE锚 与 PB锚 取较高者 + 50%保底 + 不超过现价",
             ""]

    if down:
        lines.append("### ⬇️ 建议下调")
        lines.append("")
        for a in down:
            notes_str = " ".join(a["notes"]) if a["notes"] else ""
            lines.append(
                f"**{a['name']}** {a['old']:.2f}→{a['new']:.2f}（{a['chg']:+.0f}%）| "
                f"现{a['price']:.2f} PE{a['pe_now']:.1f}(锚{a['anchor_pe']}) "
                f"PB{a['pb_now']:.2f}(锚{a['anchor_pb']})"
            )
            if notes_str:
                lines.append(f"> {notes_str}")
            lines.append("")

    if up:
        lines.append("### ⬆️ 建议上调")
        lines.append("")
        for a in up:
            lines.append(
                f"**{a['name']}** {a['old']:.2f}→{a['new']:.2f}（+{a['chg']:.0f}%）| "
                f"现{a['price']:.2f} PE{a['pe_now']:.1f}(锚{a['anchor_pe']})"
            )
            lines.append("")

    lines.append("---")
    lines.append("⚠️ 利润冰点=PE虚高，触发价以PB锚为准。需手动确认后更新。")

    state["trigger_adjustments"] = [
        {"code": a["code"], "name": a["name"],
         "old": a["old"], "suggested": a["new"],
         "change_pct": a["chg"], "notes": a["notes"],
         "date": now.strftime("%Y-%m-%d")}
        for a in adjustments
    ]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    push(f"🔧 触发价调整 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 上调{len(up)}只 下调{len(down)}只")


if __name__ == "__main__":
    main()
