"""
全市场估值温度 v3
数据源：新浪指数价格 + 乐股网 PE/PB 分位
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
    "沪深300": {"sina": "s_sh000300", "lg_code": "000300"},
    "上证50":  {"sina": "s_sh000016", "lg_code": "000016"},
    "中证500": {"sina": "s_sh000905", "lg_code": "000905"},
}


def get_sina_index(sina_code):
    """新浪指数行情"""
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={sina_code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text or '""' in text:
            return None
        data = text.split('"')[1].split(",")
        if len(data) < 5:
            return None
        price = float(data[1]) if data[1] else 0
        prev = float(data[2]) if data[2] else price
        change_pct = (price - prev) / prev * 100 if prev > 0 else 0
        return {"price": price, "chg_pct": change_pct}
    except Exception as e:
        print(f"  [新浪指数] {sina_code} 失败: {e}")
    return None


def get_legulegu_pepb(code):
    """乐股网 PE/PB 及分位"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.legulegu.com/",
        }
        # PE
        url_pe = f"https://www.legulegu.com/api/stockdata/market-index-pe-pb/get-market-index-pe-pb"
        params_pe = {"indexCode": code, "type": "pe"}
        r_pe = requests.get(url_pe, params=params_pe, headers=headers, timeout=15)
        pe_data = r_pe.json()

        # PB
        params_pb = {"indexCode": code, "type": "pb"}
        r_pb = requests.get(url_pb, params=params_pb, headers=headers, timeout=15)
        pb_data = r_pb.json()

        pe_list = pe_data.get("data", []) if isinstance(pe_data, dict) else []
        pb_list = pb_data.get("data", []) if isinstance(pb_data, dict) else []

        if not pe_list or not pb_list:
            return None

        latest_pe = pe_list[-1]
        latest_pb = pb_list[-1]

        pe_val = float(latest_pe.get("value", 0))
        pe_pct = float(latest_pe.get("percentile", 0))
        pb_val = float(latest_pb.get("value", 0))
        pb_pct = float(latest_pb.get("percentile", 0))

        return {
            "pe": pe_val,
            "pb": pb_val,
            "pe_pct": pe_pct,
            "pb_pct": pb_pct,
        }
    except Exception as e:
        print(f"  [乐股网] {code} 失败: {e}")
    return None


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def temp_label(pct):
    if pct is None:
        return "❓", ""
    if pct <= 30:
        return "🧊 低估", f"分位{pct:.0f}% → 可适当出手"
    elif pct <= 70:
        return "🌤 正常", f"分位{pct:.0f}% → 耐心等待"
    else:
        return "🔥 高估", f"分位{pct:.0f}% → 出手收紧"


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
    print(f"[START] 全市场估值温度 v3 {now:%Y-%m-%d %H:%M}")

    history = load_history()
    lines = [f"## 🌡 全市场估值温度 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    for name, cfg in INDICES.items():
        idx = get_sina_index(cfg["sina"])
        val = get_legulegu_pepb(cfg["lg_code"])

        if idx is None:
            lines.append(f"### {name}")
            lines.append("> ⚠️ 价格获取失败")
            lines.append("")
            continue

        if val is None:
            lines.append(f"### {name}")
            lines.append(f"指数 {idx['price']:,.0f} | 日涨跌{idx['chg_pct']:+.1f}%")
            lines.append("> ⚠️ PE/PB获取失败")
            lines.append("")
            continue

        pe = val["pe"]
        pb = val["pb"]
        pe_pct = val["pe_pct"]
        pb_pct = val["pb_pct"]

        pe_label, pe_advice = temp_label(pe_pct)
        pb_label, pb_advice = temp_label(pb_pct)

        avg_pct = (pe_pct + pb_pct) / 2
        if avg_pct <= 30:
            overall = "🧊 低估"
        elif avg_pct > 70:
            overall = "🔥 高估"
        else:
            overall = "🌤 正常"

        lines.append(f"### {name}")
        lines.append(f"指数 {idx['price']:,.0f} | 日涨跌{idx['chg_pct']:+.1f}%")
        lines.append(f"> PE {pe:.1f}（分位{pe_pct:.0f}%）→ {pe_label}")
        lines.append(f"> PB {pb:.2f}（分位{pb_pct:.0f}%）→ {pb_label}")
        lines.append(f"> 综合：**{overall}**")
        lines.append("")

        print(f"  {name}: {idx['price']:,.0f} PE{pe:.1f}({pe_pct:.0f}%) PB{pb:.2f}({pb_pct:.0f}%) → {overall}")

        # 累积历史
        if name not in history:
            history[name] = {"pe": [], "pb": []}
        hist = history[name]
        key = f"{today_str}:{pe:.2f}:{pe_pct:.0f}%"
        if not hist["pe"] or not hist["pe"][-1].startswith(today_str):
            hist["pe"].append(key)
            hist["pb"].append(f"{today_str}:{pb:.2f}:{pb_pct:.0f}%")
            if len(hist["pe"]) > 500:
                hist["pe"] = hist["pe"][-500:]

    save_history(history)

    max_days = max((len(history[n]["pe"]) for n in history if "pe" in history[n]), default=0)
    lines.append("---")
    lines.append("**框架联动：** 低估时触发价可适当放宽；高估时严守触发价不追高。")
    lines.append(f"📊 累积历史{max_days}天 | 下次更新：明天")

    push(f"🌡 估值温度 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
