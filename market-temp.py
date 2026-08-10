"""
全市场估值温度 v2
数据源：新浪指数价格 + 东方财富指数数据中心 PE/PB
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
    "沪深300": {"sina": "s_sh000300", "em_code": "000300"},
    "上证50":  {"sina": "s_sh000016", "em_code": "000016"},
    "中证500": {"sina": "s_sh000905", "em_code": "000905"},
}


def get_sina_index(sina_code):
    """新浪指数行情"""
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={sina_code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text:
            return None
        data = text.split('"')[1].split(",")
        if len(data) < 5:
            return None
        price = float(data[1]) if data[1] else 0
        prev = float(data[2]) if data[2] else price
        change_pct = (price - prev) / prev * 100 if prev > 0 else 0
        return {"price": price, "chg_pct": change_pct}
    except Exception as e:
        print(f"  [新浪] {sina_code} 失败: {e}")
    return None


def get_em_index_valuation(em_code):
    """东方财富指数估值分位"""
    try:
        url = "https://datacenter.eastmoney.com/api/data/get"
        params = {
            "type": "RPT_INDEX_DAILY_MARKET",
            "sty": "ALL",
            "p": 1,
            "ps": 1,
            "sr": -1,
            "st": "TRADE_DATE",
            "filter": f'(INDEX_CODE="{em_code}")',
            "source": "WEB",
            "client": "WEB",
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if not data.get("result") or not data["result"].get("data"):
            return None
        d = data["result"]["data"][0]
        return {
            "pe": float(d["PE_TTM"]) if d.get("PE_TTM") and d["PE_TTM"] != "-" else 0,
            "pb": float(d["PB_MRQ"]) if d.get("PB_MRQ") and d["PB_MRQ"] != "-" else 0,
            "pe_pct": float(d["PE_TTM_PERCENTILE"].replace("%","")) if d.get("PE_TTM_PERCENTILE") and d["PE_TTM_PERCENTILE"] != "-" else None,
            "date": d.get("TRADE_DATE", "")[:10] if d.get("TRADE_DATE") else "",
        }
    except Exception as e:
        print(f"  [东财估值] {em_code} 失败: {e}")
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
        return "❓", "?"
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
    print(f"[START] 全市场估值温度 v2 {now:%Y-%m-%d %H:%M}")

    history = load_history()
    lines = [f"## 🌡 全市场估值温度 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    for name, cfg in INDICES.items():
        idx = get_sina_index(cfg["sina"])
        val = get_em_index_valuation(cfg["em_code"])

        if idx is None or val is None:
            lines.append(f"### {name}")
            lines.append(f"> ⚠️ 数据获取失败")
            lines.append("")
            continue

        pe = val["pe"]
        pb = val["pb"]
        pe_pct = val["pe_pct"]

        pe_label, pe_advice = temp_label(pe_pct)
        pb_label, pb_advice = temp_label(pe_pct)  # 用 PE 分位近似

        overall = pe_label

        lines.append(f"### {name}")
        lines.append(f"指数 {idx['price']:,.0f} | 日涨跌{idx['chg_pct']:+.1f}%")
        lines.append(f"> PE {pe:.1f} → {pe_label}  {pe_advice}")
        lines.append(f"> PB {pb:.2f} → {pb_label}")
        lines.append(f"> 综合：**{overall}**（PE分位{pe_pct:.0f if pe_pct else '?'}%）")
        lines.append("")

        print(f"  {name}: {idx['price']:,.0f} PE{pe:.1f} PB{pb:.2f} 分位{pe_pct}% → {overall}")

        # 保存历史
        if name not in history:
            history[name] = {"pe": [], "pb": []}
        hist = history[name]
        if not hist["pe"] or not hist["pe"][-1].startswith(today_str):
            hist["pe"].append(f"{today_str}:{pe:.2f}")
            hist["pb"].append(f"{today_str}:{pb:.2f}")
            if len(hist["pe"]) > 500:
                hist["pe"] = hist["pe"][-500:]
                hist["pb"] = hist["pb"][-500:]

    save_history(history)

    max_days = max((len(history[n]["pe"]) for n in history if "pe" in history[n]), default=0)
    lines.append("---")
    lines.append("**框架联动：** 低估时触发价可适当放宽；高估时严守触发价不追高。")
    lines.append(f"📊 累积历史{max_days}天 | 下次更新：明天")

    push(f"🌡 估值温度 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
