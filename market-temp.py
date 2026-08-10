"""
全市场估值温度 v4
新浪指数价格 + 中证指数官网 PE/PB
每日 17:00 CST
"""
import os
import json
import requests
import re
from datetime import datetime, date
from pathlib import Path

DATA_FILE = Path(__file__).parent / "market_temperature.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

INDICES = {
    "沪深300": {"sina": "s_sh000300", "cs": "000300"},
    "上证50":  {"sina": "s_sh000016", "cs": "000016"},
    "中证500": {"sina": "s_sh000905", "cs": "000905"},
}


def get_sina_index(sina_code):
    """新浪指数：字段[1]=现价 [2]=涨跌额 [3]=涨跌幅%"""
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
        price = float(data[1]) if data[1] else 0
        chg_pct = float(data[3]) if data[3] else 0
        return {"price": price, "chg_pct": chg_pct}
    except Exception as e:
        print(f"  [新浪] {sina_code}: {e}")
    return None


def get_csindex_pepb(code):
    """中证指数官网 PE/PB"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.csindex.com.cn/",
        }
        url = f"https://www.csindex.com.cn/csindex-home/perf/index-perf"
        params = {
            "indexCode": code,
            "startDate": (date.today().replace(day=1) - __import__('datetime').timedelta(days=180)).strftime("%Y-%m-%d"),
            "endDate": date.today().strftime("%Y-%m-%d"),
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)
        # csindex 可能要求更多headers
        data = r.json()
        if data.get("errorCode") != "0" or not data.get("data"):
            return None
        items = data["data"]
        if not items:
            return None
        latest = items[-1]
        return {
            "pe": float(latest.get("pe1", 0)),
            "pb": float(latest.get("pb1", 0)),
            "date": latest.get("tradedate", ""),
        }
    except Exception as e:
        print(f"  [中证指数] {code}: {e}")
    return None


def get_eastmoney_pepb_alt(code):
    """东方财富指数估值-备选方案"""
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        # 指数 secid 格式：1.000300
        secid = f"1.{code}"
        params = {
            "secid": secid,
            "fields": "f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f60,f107,f115,f116,f117,f118,f119,f120,f121,f122,f168,f169,f170,f171",
            "fltt": 2,
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if not data.get("data"):
            return None
        d = data["data"]
        # 尝试多个可能的PE字段
        pe = (d.get("f115") or d.get("f116") or 0) / 100
        pb = (d.get("f117") or d.get("f118") or 0) / 100
        if pe <= 0 or pe > 1000:
            return None
        return {"pe": pe, "pb": pb}
    except:
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


def main():
    now = datetime.now()
    today_str = str(date.today())
    print(f"[START] 全市场估值温度 v4 {now:%Y-%m-%d %H:%M}")

    history = load_history()
    lines = [f"## 🌡 全市场估值温度 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    for name, cfg in INDICES.items():
        idx = get_sina_index(cfg["sina"])
        val = get_eastmoney_pepb_alt(cfg["cs"])

        if idx is None:
            lines.append(f"### {name}  ⚠️ 价格获取失败")
            lines.append("")
            continue

        price = idx["price"]
        chg = idx["chg_pct"]

        if val is None:
            lines.append(f"### {name}")
            lines.append(f"指数 {price:,.0f} | 日涨跌{chg:+.2f}%")
            lines.append("> ⚠️ PE/PB 获取失败，历史不足")
            lines.append("")

            # 累积历史（仅价格）
            h = history.setdefault(name, {"pe": []})
            if not h["pe"] or not h["pe"][-1].startswith(today_str):
                h["pe"].append(f"{today_str}:{price:.0f}")
            lines.append("")
            continue

        pe = val["pe"]
        pb = val["pb"]

        # 累积历史
        h = history.setdefault(name, {"pe": [], "pb": []})
        if not h["pe"] or not h["pe"][-1].startswith(today_str):
            h["pe"].append(f"{today_str}:{pe:.2f}")
            h["pb"].append(f"{today_str}:{pb:.2f}")
            if len(h["pe"]) > 500:
                h["pe"] = h["pe"][-500:]

        # 计算分位数
        pe_vals = [float(v.split(":")[1]) for v in h["pe"] if ":" in v]
        pb_vals = [float(v.split(":")[1]) for v in h["pb"] if ":" in v]

        def pct_calc(vals, cur):
            if len(vals) < 5 or not cur:
                return None
            return round(sum(1 for v in vals if v < cur) / len(vals) * 100, 1)

        pe_pct = pct_calc(pe_vals, pe)
        pb_pct = pct_calc(pb_vals, pb)

        def label(p):
            if p is None:
                return "❓", ""
            if p <= 30:
                return "🧊 低估", f"分位{p:.0f}% → 可适当出手"
            elif p <= 70:
                return "🌤 正常", f"分位{p:.0f}% → 耐心等待"
            else:
                return "🔥 高估", f"分位{p:.0f}% → 出手收紧"

        pe_l, pe_a = label(pe_pct)
        pb_l, pb_a = label(pb_pct)

        if pe_pct and pb_pct:
            avg = (pe_pct + pb_pct) / 2
        else:
            avg = pe_pct or pb_pct or 50
        overall = "🧊 低估" if avg <= 30 else "🔥 高估" if avg > 70 else "🌤 正常"

        lines.append(f"### {name}")
        lines.append(f"指数 {price:,.0f} | 日涨跌{chg:+.2f}%")
        pe_pct_s = f"（分位{pe_pct:.0f}%）" if pe_pct else "（累积中）"
        pb_pct_s = f"（分位{pb_pct:.0f}%）" if pb_pct else ""
        lines.append(f"> PE {pe:.1f}{pe_pct_s} → {pe_l}")
        lines.append(f"> PB {pb:.2f}{pb_pct_s} → {pb_l}")
        lines.append(f"> 综合：**{overall}**")
        lines.append("")

        print(f"  {name}: {price:,.0f} PE{pe:.1f}({pe_pct}) PB{pb:.2f}({pb_pct}) → {overall}")

    save_history(history)

    max_days = max((len(history[n]["pe"]) for n in history if "pe" in history[n]), default=0)
    lines.append("---")
    lines.append("**框架联动：** 低估时触发价可适当放宽；高估时严守触发价不追高。")
    lines.append(f"📊 累积{max_days}天 | 分位数需5天+历史")

    push(f"🌡 估值温度 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
