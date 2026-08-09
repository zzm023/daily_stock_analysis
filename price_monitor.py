"""
触发价监控 v2
联动 framework_state.json：读触发价 → 更新现价+状态 → 块状推送
每日 15:00 CST
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"

# 触发价从 framework_state.json 读取，这里只做股票→代码映射
STOCK_LIST = [
    ("000651","格力电器"),("000157","中联重科"),("600036","招商银行"),("601601","中国太保"),
    ("600018","上港集团"),("601816","京沪高铁"),("600900","长江电力"),("600941","中国移动"),
    ("002027","分众传媒"),("600066","宇通客车"),("000538","云南白药"),("300832","新产业"),
    ("688187","时代电气"),("603605","珀莱雅"),("605098","行动教育"),("603568","伟明环保"),
    ("000708","中信特钢"),("002884","凌霄泵业"),("600007","中国国贸"),("000333","美的集团"),
    ("600690","海尔智家"),("600031","三一重工"),("600309","万华化学"),("600585","海螺水泥"),
    ("000792","盐湖股份"),("603288","海天味业"),("600298","安琪酵母"),("000429","粤高速A"),
    ("600406","国电南瑞"),("600660","福耀玻璃"),("300628","亿联网络"),("600161","天坛生物"),
    ("600598","北大荒"),("002318","久立特材"),("603855","华荣股份"),("002032","苏泊尔"),
    ("002508","老板电器"),("600761","安徽合力"),("600486","扬农化工"),("600188","兖矿能源"),
    ("601058","赛轮轮胎"),("603508","思维列控"),("002601","龙佰集团"),("603806","福斯特"),
    ("600299","安迪苏"),("300124","汇川技术"),("002837","英维克"),("300627","华测导航"),
    ("002410","广联达"),("300498","温氏股份"),
]

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_price(code):
    """akshare实时价，腾讯兜底"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if not row.empty:
            return float(row.iloc[0]["最新价"])
    except Exception as e:
        print(f"  akshare {code} 失败: {e}")
    try:
        if code.startswith("6"):
            full = f"sh{code}"
        else:
            full = f"sz{code}"
        resp = requests.get(f"http://qt.gtimg.cn/q={full}", timeout=5)
        resp.encoding = "gbk"
        parts = resp.text.split("~")
        if len(parts) >= 4:
            return float(parts[3])
    except:
        pass
    return None


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger": {}, "holdings": {}}


def save_state(s):
    s["meta"] = s.get("meta", {})
    s["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("[WARN] 无TOKEN"); return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now()
    print(f"========== 触发价监控 v2 | {now:%Y-%m-%d %H:%M:%S} ==========\n")

    state = load_state()
    trigger = state.get("trigger", {})

    # ── 如果状态文件里没有触发价，用旧脚本的价格初始化 ──
    FALLBACK = {
        "000651": 38.00, "000157": 7.00, "600036": 45.58, "601601": 30.00,
        "600018": 4.00, "601816": 4.20, "600900": 21.67, "600941": 85.53,
        "002027": 5.26, "600066": 27.00, "000538": 47.00, "300832": 40.00,
        "688187": 46.00, "603605": 55.00, "605098": 48.00, "603568": 14.50,
        "000708": 13.50, "002884": 15.00, "600007": 16.46, "000333": 68.00,
        "600690": 20.00, "600031": 17.00, "600309": 68.00, "600585": 0,
        "000792": 25.00, "603288": 30.00, "600298": 35.00, "000429": 10.41,
        "600406": 15.83, "600660": 50.00, "300628": 33.00, "600161": 11.50,
        "600598": 11.50, "002318": 17.50, "603855": 15.20, "002032": 40.00,
        "002508": 14.05, "600761": 16.50, "600486": 52.00, "600188": 15.50,
        "601058": 12.00, "603508": 21.60, "002601": 13.50, "603806": 13.50,
        "600299": 7.60, "300124": 47.00, "002837": 43.00, "300627": 26.50,
        "002410": 8.50, "300498": 0,
    }

    hit, close = [], []
    total, failed = 0, 0

    for code, name in STOCK_LIST:
        tp = trigger.get(code, {}).get("trigger_price")
        if tp is None or tp == 0:
            # 首次运行：从 fallback 初始化
            fb = FALLBACK.get(code, 0)
            if fb == 0:
                continue
            tp = fb
            trigger[code] = {"name": name, "trigger_price": tp, "anchor_pct": 0,
                            "dps": 0, "current_price": 0, "gap_pct": 99, "status": "远离"}

        price = get_price(code)
        total += 1

        if price is None:
            print(f"❌ {name}({code}) 获取失败")
            failed += 1
            continue

        gap_pct = (price - tp) / tp * 100

        if price <= tp:
            status = "已触发"
            hit.append((code, name, price, tp, gap_pct))
        elif gap_pct <= 10:
            status = "接近"
            close.append((code, name, price, tp, gap_pct))
        else:
            status = "远离"

        trigger[code]["current_price"] = round(price, 2)
        trigger[code]["gap_pct"] = round(gap_pct, 2)
        trigger[code]["status"] = status

        icon = "🔴" if status == "已触发" else ("🟡" if status == "接近" else "⚪")
        print(f"{icon} {name:6s}({code}) 现价{price:>8.2f} 触发{tp:>8.2f} 差距{gap_pct:>+5.1f}% {status}")

    state["trigger"] = trigger
    save_state(state)

    print(f"\n========== 汇总 ==========")
    print(f"🔴 已触发: {len(hit)} | 🟡 接近: {len(close)} | ✅ 成功: {total-failed} | ❌ 失败: {failed}")

    # ── 块状推送 ──
    if not hit and not close:
        print("📭 无触发/接近，不推送")
        return

    lines = [f"## 📊 触发价监控 — {now:%Y.%m.%d}", "",
             f"> {now:%H:%M} | 已触发{len(hit)}只 接近{len(close)}只", ""]

    if hit:
        lines.append("### 🔴 已触发")
        lines.append("")
        for code, name, price, tp, gap in hit:
            lines.append(f"**{name}** {price:.2f}（触发价{tp:.2f}，超{abs(gap):.1f}%）")
        lines.append("")

    if close:
        lines.append("### 🟡 即将触发（≤10%）")
        lines.append("")
        for code, name, price, tp, gap in close:
            lines.append(f"**{name}** {price:.2f}（触发价{tp:.2f}，差{gap:.1f}%）")
        lines.append("")

    lines.append("> ⚠️ 触发≠买。左侧分层，目标价9折，仓位减半，观察1周。")

    t = f"🔴 触发{len(hit)}只" if hit else f"🟡 接近{len(close)}只"
    push(f"📊 {t} {now:%Y.%m.%d}", "\n".join(lines))

    print("\n[DONE]")


if __name__ == "__main__":
    main()
