"""
大宗商品价格监控 v6
数据源：腾讯期货 qt.gtimg.cn + 新浪兜底
GitHub Actions 美国IP → 只走能通的通道
"""
import os
import json
import requests
from datetime import datetime, date
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
DATA_FILE = Path(__file__).parent / "commodity_prices.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 商品 → 腾讯期货代码 → 框架股票
COMMODITIES = {
    "天然橡胶": {
        "stocks": ["601058"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "code": "RU0",
    },
    "碳酸锂": {
        "stocks": ["000792"], "level": "daily", "unit": "元/吨",
        "threshold": 0.03, "code": "LC0",
    },
    "动力煤": {
        "stocks": ["600585", "600188"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "code": "ZC0",
    },
    "螺纹钢": {
        "stocks": ["600031"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "code": "RB0",
    },
    "沪铜": {
        "stocks": ["600585"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.03, "code": "CU0",
    },
    "PTA": {
        "stocks": ["603806"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "code": "TA0",
    },
    "甲醇": {
        "stocks": ["600309"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "code": "MA0",
    },
    "豆粕": {
        "stocks": ["300498"], "level": "weekly", "unit": "元/吨",
        "threshold": 0.02, "code": "M0",
    },
}


def get_tencent_futures(code):
    """腾讯期货行情"""
    try:
        r = requests.get(f"http://qt.gtimg.cn/q=qj_{code}", timeout=15)
        r.encoding = "gbk"
        text = r.text
        if "~" not in text or '""' in text:
            return None
        parts = text.split("~")
        # 腾讯期货字段: [3]=现价 [4]=昨收 [31]=昨结
        if len(parts) < 32:
            return None
        price = float(parts[3]) if parts[3] else 0
        prev = float(parts[4]) if parts[4] else float(parts[31]) if len(parts) > 31 and parts[31] else price
        if not price or price <= 0:
            return None
        change_pct = (price - prev) / prev * 100 if prev > 0 else 0
        return {"price": price, "date": str(date.today()), "change_pct": change_pct}
    except Exception as e:
        print(f"  [腾讯期货] {code} 失败: {e}")
    return None


def get_sina_futures(code):
    """新浪兜底"""
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


def get_price(name, cfg):
    result = get_tencent_futures(cfg["code"])
    if result is None:
        result = get_sina_futures(cfg["code"])
    return result


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
    print(f"[START] 大宗商品监控 v6 {now:%Y-%m-%d %H:%M} 周{'一二三四五六日'[weekday]}")

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
        print(f"  ✅ {name}: {new_price:,.0f} {cfg['unit']}{chg_str}")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"\n  成功{ok_count}/8 失败{fail_count}")

    if not alerts:
        print("[DONE] 无商品异动")
        return

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    state["commodity_events"] = [{
        "commodity": a["name"], "price": a["price"],
        "change_str": f"{a['change_pct']:+.1f}%", "stocks": a["stocks"],
    } for a in alerts]
    state["meta"]["updated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    lines = [f"## ⚡ 商品异动 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | {len(alerts)}项异动", ""]
    for a in alerts:
        d = "📈" if a["change_pct"] > 0 else "📉"
        lines.append(f"**{a['name']}** {a['price']:,.0f} {a['unit']} "
                     f"{d}{a['change_pct']:+.1f}% → {', '.join(a['stocks'])}")
        lines.append("")
    lines.append("> 📌 已联动每日信号分析。商品数据源：腾讯期货 qt.gtimg.cn")
    push(f"⚡ 商品异动 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"\n[DONE] {len(alerts)}项异动已推送")


if __name__ == "__main__":
    main()
