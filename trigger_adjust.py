"""
触发价动态调整 v1
每季度/手动：PE分位变化 → 建议调整触发价
写入 framework_state.json → trigger_adjustments
"""
import os
import json
import requests
from datetime import datetime, date
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 框架股：code → (锚PE, 锚PB, 板块)
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
    print(f"[START] 触发价动态调整 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})

    adjustments = []
    lines = [f"## 🔧 触发价动态调整 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    for code, (anchor_pe, anchor_pb, sector) in FRAMEWORK.items():
        t = trigger.get(code)
        if not t or not isinstance(t, dict):
            continue

        name = t.get("name", code)
        old_trigger = t.get("trigger_price", 0)
        price = get_price(code)
        pe_now, pb_now = get_pe_pb(code)

        if not old_trigger or not price:
            continue

        # 计算新的理论触发价
        # 方法：锚PE × 当前EPS
        # EPS 反推 = 股价 / PE_now
        if pe_now and pe_now > 0:
            eps = price / pe_now
            new_trigger_from_pe = anchor_pe * eps
        else:
            new_trigger_from_pe = old_trigger

        if pb_now and pb_now > 0:
            bvps = price / pb_now
            new_trigger_from_pb = anchor_pb * bvps
        else:
            new_trigger_from_pb = old_trigger

        # 取两者均值作为建议触发价
        suggested = round((new_trigger_from_pe + new_trigger_from_pb) / 2, 2)
        change_pct = round((suggested - old_trigger) / old_trigger * 100, 1)

        # 只有变化超过 5% 才推送
        if abs(change_pct) >= 5:
            direction = "⬆️" if change_pct > 0 else "⬇️"
            adjustments.append({
                "code": code, "name": name, "old_trigger": old_trigger,
                "suggested": suggested, "change_pct": change_pct,
                "direction": direction, "sector": sector,
                "pe_now": pe_now, "pb_now": pb_now,
                "anchor_pe": anchor_pe, "anchor_pb": anchor_pb,
            })

    if not adjustments:
        lines.append("✅ 所有触发价合理，无需调整。")
        lines.append("")
        lines.append("> 基准：锚PE/PB × 当前EPS/BVPS。变动 <5% 不报告。")
    else:
        adjustments.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        lines.append("| 股票 | 代码 | 旧触发 | 建议 | 变动 | 原因 |")
        lines.append("|------|------|--------|------|------|------|")
        for a in adjustments:
            reason = f"PE{a['pe_now']:.1f}(锚{a['anchor_pe']}) PB{a['pb_now']:.2f}(锚{a['anchor_pb']})"
            lines.append(
                f"| {a['name']} | {a['code']} | {a['old_trigger']:.2f} | "
                f"{a['suggested']:.2f} | {a['direction']}{a['change_pct']:+.1f}% | {reason} |"
            )
        lines.append("")
        lines.append("### 📝 调整逻辑")
        lines.append("建议触发价 = (锚PE×EPS + 锚PB×BVPS) / 2")
        lines.append("EPS从当前PE反推，BVPS从当前PB反推。")
        lines.append("")
        lines.append("⚠️ **需手动确认**后更新 framework_state.json。")

        # 写入建议
        state["trigger_adjustments"] = [
            {"code": a["code"], "name": a["name"],
             "old": a["old_trigger"], "suggested": a["suggested"],
             "change_pct": a["change_pct"], "date": now.strftime("%Y-%m-%d")}
            for a in adjustments
        ]
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    push(f"🔧 触发价调整 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(adjustments)}只建议调整")


if __name__ == "__main__":
    main()
