"""
全市场估值温度 v5
新浪指数价格 + 乐股网 PE/PB 分位（带原始返回调试）
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
    "沪深300": {"sina": "s_sh000300", "lg": "000300"},
    "上证50":  {"sina": "s_sh000016", "lg": "000016"},
    "中证500": {"sina": "s_sh000905", "lg": "000905"},
}


def get_sina_index(sina_code):
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={sina_code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text or '""' in text:
            return None
        data = text.split('"')[1].split(",")
        if len(data) < 4:
            return None
        return {
            "price": float(data[1]) if data[1] else 0,
            "chg_pct": float(data[3]) if data[3] else 0,
        }
    except Exception as e:
        print(f"  [新浪] {sina_code}: {e}")
    return None


def get_legulegu(code):
    """乐股网 PE/PB 分位"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    results = {}
    for typ in ("pe", "pb"):
        try:
            url = "https://www.legulegu.com/api/stockdata/market-index-pe-pb/get-market-index-pe-pb"
            params = {"indexCode": code, "type": typ}
            r = requests.get(url, params=params, headers=headers, timeout=15)
            obj = r.json()
            # 调试：打印原始返回前200字符
            raw_snippet = json.dumps(obj, ensure_ascii=False)[:200]
            print(f"  [乐股 {typ}] {code}: {raw_snippet}")
            
            data_list = obj.get("data", [])
            if not data_list:
                # 可能嵌套在 result.data 里
                data_list = obj.get("result", {}).get("data", [])
            if not data_list:
                continue
            latest = data_list[-1]
            val = float(latest.get("value", latest.get("pe", latest.get("pb", 0))))
            pct = float(latest.get("percentile", latest.get("quantile", 50)))
            results[typ] = {"value": val, "percentile": pct}
        except Exception as e:
            print(f"  [乐股 {typ}] {code} 异常: {e}")
    
    if results:
        return {
            "pe": results.get("pe", {}).get("value", 0),
            "pb": results.get("pb", {}).get("value", 0),
            "pe_pct": results.get("pe", {}).get("percentile"),
            "pb_pct": results.get("pb", {}).get("percentile"),
        }
    return None


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def label(pct):
    if pct is None:
        return "❓", ""
    if pct <= 30:
        return "🧊 低估", f"分位{pct:.0f}% → 可适当出手"
    elif pct <= 70:
        return "🌤 正常", f"分位{pct:.0f}% → 耐心等待"
    else:
        return "🔥 高估", f"分位{pct:.0f}% → 出手收紧"


def main():
    now = datetime.now()
    today_str = str(date.today())
    print(f"[START] 全市场估值温度 v5 {now:%Y-%m-%d %H:%M}")

    history = load_history()
    lines = [f"## 🌡 全市场估值温度 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    for name, cfg in INDICES.items():
        idx = get_sina_index(cfg["sina"])
        val = get_legulegu(cfg["lg"])

        if idx is None:
            lines.append(f"### {name}  ⚠️ 价格失败")
            lines.append("")
            continue

        price = idx["price"]
        chg = idx["chg_pct"]

        if val is None:
            lines.append(f"### {name}")
            lines.append(f"指数 {price:,.0f} | 涨跌{chg:+.2f}%")
            lines.append("> ⚠️ PE/PB 获取失败")
            lines.append("")
            continue

        pe = val["pe"]; pe_pct = val["pe_pct"]
        pb = val["pb"]; pb_pct = val["pb_pct"]

        pe_l, _ = label(pe_pct)
        pb_l, _ = label(pb_pct)

        avg = (pe_pct or 50 + pb_pct or 50) / 2 if pe_pct and pb_pct else (pe_pct or pb_pct or 50)
        overall = "🧊 低估" if avg <= 30 else "🔥 高估" if avg > 70 else "🌤 正常"

        lines.append(f"### {name}")
        lines.append(f"指数 {price:,.0f} | 涨跌{chg:+.2f}%")
        pe_s = f"PE {pe:.1f}（分位{pe_pct:.0f}%）" if pe_pct else f"PE {pe:.1f}"
        pb_s = f"PB {pb:.2f}（分位{pb_pct:.0f}%）" if pb_pct else f"PB {pb:.2f}"
        lines.append(f"> {pe_s} → {pe_l}")
        lines.append(f"> {pb_s} → {pb_l}")
        lines.append(f"> 综合：**{overall}**")
        lines.append("")

        print(f"  {name}: {price:,.0f} PE{pe:.1f}({pe_pct}%) PB{pb:.2f}({pb_pct}%) → {overall}")

        # 保存
        h = history.setdefault(name, {"pe": [], "pb": []})
        if not h["pe"] or not h["pe"][-1].startswith(today_str):
            h["pe"].append(f"{today_str}:{pe:.2f}")
            h["pb"].append(f"{today_str}:{pb:.2f}")

    save_history(history)

    max_d = max((len(history[n]["pe"]) for n in history if "pe" in history[n]), default=0)
    lines.append("---")
    lines.append("**框架联动：** 低估时触发价可适当放宽；高估时严守触发价不追高。")
    lines.append(f"📊 累积{max_d}天 | 乐股网 legulegu.com")

    push(f"🌡 估值温度 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
