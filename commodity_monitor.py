"""
大宗商品价格监控 v3
数据源：新浪期货 + 生意社现货 | 无 akshare 依赖
异动写入 framework_state.json → daily_signal.py 联动
"""
import os
import json
import requests
import re
from datetime import datetime, date
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
DATA_FILE = Path(__file__).parent / "commodity_prices.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 商品配置
COMMODITIES = {
    "碳酸锂": {
        "stocks": ["000792"], "level": "daily", "unit": "元/吨",
        "threshold": 0.03, "source": "sina_futures", "code": "LC0",
    },
    "聚合MDI": {
        "stocks": ["600309"], "level": "daily", "unit": "元/吨",
        "threshold": 0.02, "source": "100ppi", "ppid": "264",
    },
    "钛白粉(金红石型)": {
        "stocks": ["002601"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "source": "100ppi", "ppid": "764",
    },
    "蛋氨酸": {
        "stocks": ["600299"], "level": "weekly", "unit": "元/公斤",
        "threshold": 0.03, "source": "100ppi", "ppid": "843",
    },
    "PO42.5水泥": {
        "stocks": ["600585"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "source": "100ppi", "ppid": "308",
    },
    "动力煤(5500大卡)": {
        "stocks": ["600585", "600188"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "source": "100ppi", "ppid": "345",
    },
    "氯化钾": {
        "stocks": ["000792"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.03, "source": "100ppi", "ppid": "389",
    },
    "EVA光伏料": {
        "stocks": ["603806"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "source": "100ppi", "ppid": "1139",
    },
    "天然橡胶": {
        "stocks": ["601058"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "source": "sina_futures", "code": "RU0",
    },
}


def get_sina_futures(code):
    """新浪期货连续合约"""
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text:
            return None
        data = text.split('"')[1].split(",") if '"' in text else text.split(",")[1:]
        if len(data) < 6 or not data[0]:
            return None
        price = float(data[3]) if data[3] else float(data[1]) if data[1] else 0
        prev = float(data[4]) if data[4] and data[4] != "0.000" else price
        change_pct = (price - prev) / prev * 100 if prev and prev > 0 else 0
        return {"price": price, "date": str(date.today()), "change_pct": change_pct}
    except Exception as e:
        print(f"  [新浪期货] {code} 失败: {e}")
    return None


def get_100ppi(ppid, name):
    """生意社现货价格"""
    try:
        url = f"https://www.100ppi.com/price/detail-{ppid}.html"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.encoding = "utf-8"
        text = r.text
        patterns = [
            r'<span class="price"[^>]*>(\d+[\.\d]*)</span>',
            r'最新价格[：:]\s*(\d+[\.\d]*)',
            r'参考价[：:]\s*(\d+[\.\d]*)',
            r'<td[^>]*class="[^"]*price[^"]*"[^>]*>(\d+[\.\d]*)</td>',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return {"price": float(m.group(1)), "date": str(date.today()), "change_pct": 0}
        print(f"  [100ppi] {name}({ppid}) 未匹配到价格")
    except Exception as e:
        print(f"  [100ppi] {name}({ppid}) 失败: {e}")
    return None


def get_price(name, cfg):
    if cfg["source"] == "sina_futures":
        return get_sina_futures(cfg["code"])
    elif cfg["source"] == "100ppi":
        return get_100ppi(cfg["ppid"], name)
    return None


def push(title, content):
    if not PUSHPLUS_TOKEN: return
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
    weekday = now.weekday()
    print(f"[START] 大宗商品监控 v3 {now:%Y-%m-%d %H:%M} 周{'一二三四五六日'[weekday]}")

    history = {}
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

    alerts = []
    snapshot = {}

    for name, cfg in COMMODITIES.items():
        # 非周一跳过周度商品
        if cfg["level"] == "weekly" and weekday != 0:
            snapshot[name] = history.get(name, {})
            continue

        print(f"\n  [{name}] ...")
        result = get_price(name, cfg)
        if result is None:
            snapshot[name] = history.get(name, {})
            continue

        new_price = result["price"]
        old = history.get(name, {})
        old_price = old.get("price")

        chg_str = ""
        if old_price and old_price > 0:
            chg = (new_price - old_price) / old_price
            chg_str = f" {chg*100:+.1f}%"
            if abs(chg) >= cfg["threshold"]:
                alerts.append({
                    "name": name, "price": new_price, "old_price": old_price,
                    "change_pct": round(chg * 100, 1),
                    "stocks": cfg["stocks"], "unit": cfg["unit"],
                })

        snapshot[name] = {"price": new_price, "date": result["date"], "unit": cfg["unit"]}
        print(f"    {new_price:,.0f} {cfg['unit']}{chg_str}")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    # ── 有告警才推送 ──
    if not alerts:
        print("\n[DONE] 无商品异动")
        return

    # ── 写 events 供每日信号联动 ──
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    comm_events = []
    for a in alerts:
        comm_events.append({
            "commodity": a["name"],
            "price": a["price"],
            "change_str": f"{a['change_pct']:+.1f}%",
            "stocks": a["stocks"],
        })
    state["commodity_events"] = comm_events
    state["meta"] = state.get("meta", {})
    state["meta"]["updated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ── 推送 ──
    lines = [f"## ⚡ 商品异动 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | {len(alerts)}项异动", ""]
    for a in alerts:
        dir_sign = "📈" if a["change_pct"] > 0 else "📉"
        stocks_str = ", ".join(a["stocks"])
        lines.append(
            f"**{a['name']}** {a['price']:,.0f} {a['unit']} "
            f"{dir_sign}{a['change_pct']:+.1f}% → {stocks_str}"
        )
        lines.append("")
    lines.append("> 📌 已写入 commodity_events，每日信号将联动分析。")

    push(f"⚡ 商品异动 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"\n[DONE] {len(alerts)}项异动已推送")


if __name__ == "__main__":
    main()
