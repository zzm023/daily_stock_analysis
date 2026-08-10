"""
全市场估值温度 v6
数据源：新浪指数价格 + 自累积分位数
每日 17:00 CST
无外部 PE/PB 依赖，适合海外 IP
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
    "沪深300": "s_sh000300",
    "上证50":  "s_sh000016",
    "中证500": "s_sh000905",
    "创业板指": "s_sz399006",
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


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def calc_percentile(values, current):
    if len(values) < 20 or not current:
        return None
    below = sum(1 for v in values if v < current)
    return round(below / len(values) * 100, 1)


def label(pct):
    if pct is None:
        return "❓ 累积中（需20天+）", ""
    if pct <= 25:
        return "🧊 低估", f"价格分位{pct:.0f}% → 可适当出手"
    elif pct <= 70:
        return "🌤 正常", f"价格分位{pct:.0f}% → 耐心等待"
    else:
        return "🔥 高估", f"价格分位{pct:.0f}% → 出手收紧"


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
    print(f"[START] 全市场估值温度 v6 {now:%Y-%m-%d %H:%M}")

    history = load_history()
    lines = [f"## 🌡 全市场估值温度 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M}", ""]

    for name, sina_code in INDICES.items():
        idx = get_sina_index(sina_code)
        if idx is None:
            continue

        price = idx["price"]
        chg = idx["chg_pct"]

        # 累积历史
        h = history.setdefault(name, [])
        if not h or not h[-1].startswith(today_str):
            h.append(f"{today_str}:{price:.0f}")
            if len(h) > 500:
                h = h[-500:]
                history[name] = h

        prices = [float(v.split(":")[1]) for v in h]
        pct = calc_percentile(prices, price)
        lbl, adv = label(pct)

        lines.append(f"### {name}")
        lines.append(f"指数 {price:,.0f} | 涨跌{chg:+.2f}%")
        lines.append(f"> {lbl}  {adv}")
        lines.append("")

        print(f"  {name}: {price:,.0f} 分位{pct}% → {lbl}")

    save_history(history)

    max_d = max((len(history[n]) for n in history if isinstance(history.get(n), list)), default=0)
    need_more = max(0, 20 - max_d)

    lines.append("---")
    lines.append("📌 基于价格分位（非 PE/PB 估值分位）：历史价格低位=有安全边际。")
    lines.append(f"📊 累积{max_d}天" + (f" | 还需{need_more}天达有效分位" if need_more else " | 分位数有效✅"))
    lines.append("")
    lines.append("**框架联动：** 多指数低估时触发价放宽5-10%；全面高估时收紧。")
    lines.append("> 数据源：新浪指数行情 | 自累积分位 | 不受国内 IP 限制")

    push(f"🌡 估值温度 {now:%Y.%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
