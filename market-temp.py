"""
全市场估值温度 v1
沪深300/上证50 PE/PB + 历史分位数 → 定投节奏建议
每日 17:00 CST
"""
import os
import json
import requests
from datetime import datetime, date
from pathlib import Path

DATA_FILE = Path(__file__).parent / "market_temperature.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

INDICES = {
    "沪深300": "1.000300",
    "上证50":  "1.000016",
    "中证500": "1.000905",
}


def get_index_pe_pb(secid):
    """东方财富指数PE/PB"""
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {"secid": secid, "fields": "f43,f44,f115,f117,f119,f120,f121,f169"}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if not data.get("data"):
            return None
        d = data["data"]
        return {
            "price": d.get("f43", 0) / 100 if d.get("f43") else 0,
            "pe": d.get("f115", 0) / 100 if d.get("f115") else 0,
            "pb": d.get("f117", 0) / 100 if d.get("f117") else 0,
            "chg_pct": d.get("f169", 0) / 100 if d.get("f169") else 0,
        }
    except Exception as e:
        print(f"  [东财] {secid} 失败: {e}")
    return None


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def calc_percentile(values, current):
    if not values or not current:
        return None
    below = sum(1 for v in values if v < current)
    return round(below / len(values) * 100, 1)


def temp_label(pct):
    if pct is None:
        return "?", "—"
    if pct <= 30:
        return "🧊 低估", f"分位{pct}% → 可适当出手"
    elif pct <= 70:
        return "🌤 正常", f"分位{pct}% → 耐心等待"
    else:
        return "🔥 高估", f"分位{pct}% → 出手收紧"


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
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
    today_str = str(date.today())
    print(f"[START] 全市场估值温度 v1 {now:%Y-%m-%d %H:%M}")

    history = load_history()
    lines = [f"## 🌡 全市场估值温度 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    for name, secid in INDICES.items():
        result = get_index_pe_pb(secid)
        if result is None:
            continue

        pe = result["pe"]
        pb = result["pb"]

        if name not in history:
            history[name] = {"pe": [], "pb": []}
        hist = history[name]

        if not hist["pe"] or not hist["pe"][-1].startswith(today_str):
            hist["pe"].append(f"{today_str}:{pe:.2f}")
            hist["pb"].append(f"{today_str}:{pb:.2f}")
            if len(hist["pe"]) > 500:
                hist["pe"] = hist["pe"][-500:]
                hist["pb"] = hist["pb"][-500:]

        pe_vals = [float(v.split(":")[1]) for v in hist["pe"] if ":" in v]
        pb_vals = [float(v.split(":")[1]) for v in hist["pb"] if ":" in v]

        pe_pct = calc_percentile(pe_vals, pe)
        pb_pct = calc_percentile(pb_vals, pb)

        pe_label, pe_advice = temp_label(pe_pct)
        pb_label, pb_advice = temp_label(pb_pct)

        avg_pct = (pe_pct or 50) if pe_pct else (pb_pct or 50)
        if pe_pct and pb_pct:
            avg_pct = (pe_pct + pb_pct) / 2
        overall = "🧊 低估" if avg_pct <= 30 else "🔥 高估" if avg_pct > 70 else "🌤 正常"

        lines.append(f"### {name}")
        lines.append(f"指数 {result['price']:,.0f} | 日涨跌{result['chg_pct']:+.1f}%")
        lines.append(f"> PE {pe:.1f} → {pe_label}  {pe_advice}")
        lines.append(f"> PB {pb:.2f} → {pb_label}  {pb_advice}")
        lines.append(f"> 综合：**{overall}**")
        lines.append("")

        print(f"  {name}: PE{pe:.1f}(分位{pe_pct}%) PB{pb:.2f}(分位{pb_pct}%) → {overall}")

    save_history(history)

    max_days = max((len(history[n]["pe"]) for n in history if "pe" in history[n]), default=0)
    lines.append("---")
    lines.append("**框架联动：** 估值偏低时触发价可适当放宽；估值偏高时严守触发价不追高。")
    lines.append(f"📊 累积历史{max_days}天 | 下次更新：明天")

    push(f"🌡 估值温度 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
