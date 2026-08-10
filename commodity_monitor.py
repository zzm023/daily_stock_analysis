"""
大宗商品价格监控 v5
数据源：新浪期货 + 100ppi（长超时+移动端兜底）
GitHub Actions 美国IP限制：现货可能部分不可达
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

COMMODITIES = {
    "碳酸锂": {
        "stocks": ["000792"], "level": "daily", "unit": "元/吨",
        "threshold": 0.03, "source": "sina_futures", "code": "LC2507",
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def get_sina_futures(code):
    """新浪期货"""
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=15)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text or '""' in text:
            return None
        data = text.split('"')[1].split(",")
        if len(data) < 9 or not data[0]:
            return None
        price = float(data[3]) if data[3] and data[3] != "0.000" else float(data[8]) if len(data) > 8 and data[8] else 0
        prev = float(data[8]) if len(data) > 8 and data[8] and data[8] != "0.000" else price
        if not price:
            return None
        change_pct = (price - prev) / prev * 100 if prev > 0 else 0
        return {"price": price, "date": str(date.today()), "change_pct": change_pct}
    except Exception as e:
        print(f"  [新浪] {code} 失败: {e}")
    return None


def get_100ppi(ppid, name):
    """生意社现货 — 两步走：移动端 → 趋势表"""
    urls = [
        (f"https://www.100ppi.com/price/detail-{ppid}.html", [
            r'class="price"[^>]*>(\d+[\.\d]*)<',
            r'参考报价[：:]\s*(\d+[\.\d]*)',
        ]),
        (f"https://www.100ppi.com/price/trend/{ppid}-1.html", [
            r'<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>(\d+[\.\d]*)</td>',
        ]),
    ]
    for url, patterns in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.encoding = "utf-8"
            text = r.text
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    price = float(m.group(2)) if m.lastindex >= 2 else float(m.group(1))
                    if price > 0:
                        return {"price": price, "date": str(date.today()), "change_pct": 0}
        except Exception as e:
            print(f"  [100ppi] {url} 超时")
    print(f"  [100ppi] {name}({ppid}) 所有页面均失败")
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
    print(f"[START] 大宗商品监控 v5 {now:%Y-%m-%d %H:%M} 周{'一二三四五六日'[weekday]}")

    history = {}
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

    alerts = []
    snapshot = {}
    ok_count = 0
    fail_count = 0

    for name, cfg in COMMODITIES.items():
        if cfg["level"] == "weekly" and weekday != 0:
            snapshot[name] = history.get(name, {})
            continue

        print(f"\n  [{name}] ...")
        result = get_price(name, cfg)
        if result is None:
            snapshot[name] = history.get(name, {})
            fail_count += 1
            continue

        ok_count += 1
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
        print(f"    ✅ {new_price:,.0f} {cfg['unit']}{chg_str}")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"\n  成功{ok_count}/9 失败{fail_count}")

    if not alerts:
        print("[DONE] 无商品异动")
        return

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    state["commodity_events"] = [{
        "commodity": a["name"], "price": a["price"],
        "change_str": f"{a['change_pct']:+.1f}%", "stocks": a["stocks"],
    } for a in alerts]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    lines = [f"## ⚡ 商品异动 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | {len(alerts)}项异动", ""]
    for a in alerts:
        d = "📈" if a["change_pct"] > 0 else "📉"
        lines.append(f"**{a['name']}** {a['price']:,.0f} {a['unit']} "
                     f"{d}{a['change_pct']:+.1f}% → {', '.join(a['stocks'])}")
        lines.append("")
    lines.append("> 📌 已联动每日信号分析。")
    push(f"⚡ 商品异动 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"\n[DONE] {len(alerts)}项异动已推送")


if __name__ == "__main__":
    main()
