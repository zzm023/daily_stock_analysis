"""
触发价动态调整 v2
修正：PB低于锚时不拉高 / 涨幅>30%标记重评
每季度/手动
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
    "600036": (8, 1.0, "银行"), "601601": (8, 1.0, "保险"),
    "600018": (15, 0.9, "港口"), "601816": (20, 1.0, "铁路"),
    "600900": (18, 2.0, "水电"), "600941": (12, 1.0, "电信"),
    "600406": (20, 2.0, "电力设备"), "600598": (20, 2.5, "农业"),
    "603568": (20, 3.0, "环保"), "600007": (18, 1.5, "商业地产"),
    "000429": (12, 1.2, "高速"), "000157": (15, 1.5, "工程机械"),
    "600585": (15, 0.8, "水泥"), "000792": (30, 2.0, "锂盐"),
    "600188": (8, 1.0, "煤炭"), "002601": (18, 2.0, "钛白粉"),
    "600299": (20, 1.5, "氨基酸"), "300498": (15, 1.5, "养殖"),
    "000651": (10, 1.5, "家电"), "600066": (12, 1.5, "客车"),
    "000333": (12, 2.0, "家电"), "600690": (13, 1.8, "家电"),
    "600031": (12, 1.5, "工程机械"), "600309": (18, 2.5, "MDI"),
    "600660": (15, 2.0, "汽车玻璃"), "600761": (12, 1.5, "叉车"),
    "600486": (18, 2.0, "农药"), "601058": (15, 1.5, "轮胎"),
    "603806": (20, 2.5, "光伏材料"), "000708": (14, 1.8, "特钢"),
    "002027": (14, 3.0, "楼宇媒体"), "000538": (20, 2.0, "中药"),
    "603605": (25, 5.0, "化妆品"), "605098": (18, 3.0, "管理培训"),
    "600298": (22, 2.5, "酵母"), "300628": (18, 3.0, "通信"),
    "002508": (15, 2.0, "厨电"), "002032": (18, 3.0, "炊具"),
    "002884": (15, 1.5, "水泵"), "002318": (15, 2.0, "钢管"),
    "603855": (16, 2.0, "防爆"), "603288": (35, 5.0, "调味品"),
    "603508": (15, 1.5, "铁路信号"),
    "600161": (19, 3.0, "血制品"),
    "300832": (30, 4.0, "医疗器械"), "688187": (25, 2.5, "轨交芯片"),
    "300124": (30, 4.0, "工控"), "002837": (30, 4.0, "温控"),
    "300627": (30, 4.0, "导航"), "002410": (40, 4.0, "建筑软件"),
}


def get_pe_pb(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) < 45:
            return 0, 0
        pe = float(parts[39]) if parts[39] and parts[39] != "0.00" else 0
        pb = float(parts[43]) if parts[43] and parts[43] != "0.00" else 0
        return pe, pb
    except:
        return 0, 0


def get_price(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) >= 4 and parts[3]:
            return float(parts[3])
    except:
        pass
    return 0


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
    print(f"[START] 触发价动态调整 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})

    adjustments = []

    for code, (anchor_pe, anchor_pb, sector) in FRAMEWORK.items():
        t = trigger.get(code)
        if not t or not isinstance(t, dict):
            continue

        name = t.get("name", code)
        old_trigger = t.get("trigger_price", 0)
        price = get_price(code)
        pe_now, pb_now = get_pe_pb(code)

        if not old_trigger or not price or not pe_now or not pb_now:
            continue

        # PE 维度：锚PE × (股价/当前PE)
        eps = price / pe_now
        trigger_pe = anchor_pe * eps

        # PB 维度：锚PB × (股价/当前PB)，但 PB < 锚时保底=股价（不拉高）
        bvps = price / pb_now
        if pb_now < anchor_pb:
            trigger_pb = price  # PB已低估，不借PB拉高触发
        else:
            trigger_pb = anchor_pb * bvps

        # 取两者较低值（保守）
        suggested = round(min(trigger_pe, trigger_pb), 2)
        change_pct = round((suggested - old_trigger) / old_trigger * 100, 1)

        if abs(change_pct) >= 10:
            direction = "⬆️" if change_pct > 0 else "⬇️"
            note = ""
            if change_pct > 30:
                note = "⚠️ 旧价严重过时"
            elif change_pct < -20:
                note = "⚠️ 估值恶化"

            adjustments.append({
                "code": code, "name": name, "old": old_trigger,
                "new": suggested, "chg": change_pct,
                "dir": direction, "pe_now": pe_now, "anchor_pe": anchor_pe,
                "pb_now": pb_now, "anchor_pb": anchor_pb, "note": note,
            })

    if not adjustments:
        lines = ["## 🔧 触发价动态调整 — 无需调整", "",
                 "✅ 所有触发价与当前估值一致，变动 <10%。"]
        push(f"🔧 触发价调整 {now:%Y.%m.%d}", "\n".join(lines))
        print("[DONE] 无需调整")
        return

    adjustments.sort(key=lambda x: abs(x["chg"]), reverse=True)

    lines = [f"## 🔧 触发价调整建议 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | {len(adjustments)}只变动≥10%", "",
             "> 逻辑：锚PE×当前EPS 与 现价(如PB已低估) 取较低值",
             ""]

    for a in adjustments:
        pe_info = f"PE{a['pe_now']:.1f}(锚{a['anchor_pe']})"
        pb_info = f"PB{a['pb_now']:.2f}(锚{a['anchor_pb']})"
        lines.append(
            f"**{a['name']}** {a['dir']}{a['chg']:+.1f}% | "
            f"旧{a['old']:.2f} → 新{a['new']:.2f} | {pe_info} {pb_info}"
        )
        if a["note"]:
            lines.append(f"> {a['note']}")
        lines.append("")

    lines.append("---")
    lines.append("⚠️ 涨幅>30%说明旧触发价严重过时。**需手动确认**后更新。")
    lines.append("> 已写入 framework_state.json → trigger_adjustments")

    state["trigger_adjustments"] = [
        {"code": a["code"], "name": a["name"],
         "old": a["old"], "suggested": a["new"],
         "change_pct": a["chg"], "date": now.strftime("%Y-%m-%d")}
        for a in adjustments
    ]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    push(f"🔧 触发价调整 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(adjustments)}只建议调整")


if __name__ == "__main__":
    main()
