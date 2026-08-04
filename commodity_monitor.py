#!/usr/bin/env python3
"""
大宗商品价格监控脚本
监控9个商品 → 8只框架股票
周期：碳酸锂+MDI每天；其余每周一
"""

import requests
import json
import os
import re
from datetime import datetime, date
from pathlib import Path

COMMODITIES = {
    "碳酸锂": {
        "stocks": ["盐湖股份(000792)"],
        "level": "daily",
        "unit": "元/吨",
        "threshold": 0.03,
        "source": "futures",
        "code": "LC",
    },
    "聚合MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "100ppi",
        "ppid": "264",
    },
    "纯MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "100ppi",
        "ppid": "265",
    },
    "钛白粉(金红石型)": {
        "stocks": ["龙佰集团(002601)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "100ppi",
        "ppid": "764",
    },
    "蛋氨酸": {
        "stocks": ["安迪苏(600299)"],
        "level": "weekly",
        "unit": "元/公斤",
        "threshold": 0.03,
        "source": "100ppi",
        "ppid": "843",
    },
    "PO42.5水泥": {
        "stocks": ["海螺水泥(600585)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "100ppi",
        "ppid": "308",
    },
    "动力煤(5500大卡)": {
        "stocks": ["海螺水泥(600585)", "兖矿能源(600188)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "100ppi",
        "ppid": "345",
    },
    "氯化钾": {
        "stocks": ["盐湖股份(000792)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.03,
        "source": "100ppi",
        "ppid": "389",
    },
    "EVA光伏料": {
        "stocks": ["福斯特(603806)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "100ppi",
        "ppid": "1139",
    },
    "天然橡胶": {
        "stocks": ["赛轮轮胎(601058)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "futures",
        "code": "RU",
    },
}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
DATA_FILE = Path(__file__).parent / "commodity_prices.json"


def get_futures_price(code):
    try:
        import akshare as ak
        df = ak.futures_main_sina(symbol=code)
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            return {
                "price": float(latest["收盘价"]),
                "date": str(latest["日期"]) if "日期" in df.columns else str(date.today()),
                "change_pct": float(latest.get("涨跌幅", 0)),
            }
    except Exception as e:
        print(f"  [akshare期货] {code} 获取失败: {e}")
    return None


def get_100ppi_price(ppid, name):
    try:
        url = f"https://www.100ppi.com/price/detail-{ppid}.html"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "utf-8"
        text = resp.text

        patterns = [
            r'<span class="price"[^>]*>(\d+[\.\d]*)</span>',
            r'最新价格[：:]\s*(\d+[\.\d]*)',
            r'参考价[：:]\s*(\d+[\.\d]*)',
            r'<td[^>]*class="[^"]*price[^"]*"[^>]*>(\d+[\.\d]*)</td>',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return {"price": float(m.group(1)), "date": str(date.today()), "change_pct": None}
        print(f"  [100ppi] {name}({ppid}) 未匹配到价格")
    except Exception as e:
        print(f"  [100ppi] {name}({ppid}) 请求失败: {e}")
    return None


def get_commodity_price(name, cfg):
    if cfg["source"] == "futures":
        return get_futures_price(cfg["code"])
    elif cfg["source"] == "100ppi":
        return get_100ppi_price(cfg["ppid"], name)
    return None


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def pushplus_send(title, content):
    if not PUSHPLUS_TOKEN:
        print("  [PushPlus] 未配置TOKEN，跳过推送")
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        result = r.json()
        if result.get("code") == 200:
            print(f"  [PushPlus] 推送成功")
        else:
            print(f"  [PushPlus] 推送失败: {result}")
    except Exception as e:
        print(f"  [PushPlus] 推送异常: {e}")


def should_check_today(cfg):
    if cfg["level"] == "daily":
        return True
    return datetime.now().weekday() == 0


def main():
    print(f"=== 大宗商品价格监控 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"星期: {['一','二','三','四','五','六','日'][datetime.now().weekday()]}")

    history = load_history()
    alerts = []
    weekly_items = []
    all_data = {}

    for name, cfg in COMMODITIES.items():
        if not should_check_today(cfg):
            all_data[name] = history.get(name, {})
            continue

        print(f"\n[{name}] 获取中...")
        result = get_commodity_price(name, cfg)

        if result is None:
            print(f"  ❌ 获取失败，跳过")
            all_data[name] = history.get(name, {})
            continue

        new_price = result["price"]
        old_data = history.get(name, {})
        old_price = old_data.get("price")

        record = {
            "price": new_price,
            "date": result["date"],
            "unit": cfg["unit"],
            "stocks": ", ".join(cfg["stocks"]),
            "_name": name,
        }
        all_data[name] = record

        print(f"  ✅ {new_price:,.0f} {cfg['unit']}")

        if old_price and old_price > 0:
            change_pct = (new_price - old_price) / old_price
            record["change_pct"] = round(change_pct, 4)
            direction = "↑" if change_pct > 0 else "↓" if change_pct < 0 else "→"
            print(f"     上次: {old_price:,.0f}  |  变动: {direction} {abs(change_pct)*100:.1f}%")

            if abs(change_pct) >= cfg["threshold"]:
                alerts.append({
                    "name": name,
                    "price": new_price,
                    "old_price": old_price,
                    "change_pct": change_pct,
                    "stocks": cfg["stocks"],
                    "unit": cfg["unit"],
                })

        if cfg["level"] == "weekly" and datetime.now().weekday() == 0:
            weekly_items.append(record)

    save_history(all_data)

    if not alerts and not weekly_items:
        print("\n无告警，无周报，不推送。")
        return

    content_parts = []

    if alerts:
        content_parts.append(f"## ⚠️ 商品价格告警 ({len(alerts)}项)")
        content_parts.append("")
        content_parts.append("| 商品 | 现价 | 变动 | 影响股票 |")
        content_parts.append("|------|------|------|----------|")
        for a in alerts:
            direction = "📈" if a["change_pct"] > 0 else "📉"
            content_parts.append(
                f"| {a['name']} | {a['price']:,.0f} {a['unit']} | "
                f"{direction} {a['change_pct']*100:+.1f}% | "
                f"{', '.join(a['stocks'])} |"
            )
        content_parts.append("")

    if weekly_items and datetime.now().weekday() == 0:
        content_parts.append(f"## 📋 周度商品价格总览")
        content_parts.append("")
        content_parts.append("| 商品 | 现价 | 影响股票 |")
        content_parts.append("|------|------|----------|")
        for item in weekly_items:
            content_parts.append(
                f"| {item.get('_name', '')} | {item['price']:,.0f} {item['unit']} | "
                f"{item['stocks']} |"
            )

        daily_in_weekly = []
        for name, data in all_data.items():
            cfg = COMMODITIES.get(name, {})
            if cfg.get("level") == "daily" and data:
                daily_in_weekly.append(f"| {name} | {data['price']:,.0f} {cfg['unit']} | {data['stocks']} |")
        if daily_in_weekly:
            content_parts.append("")
            content_parts.append("### 每日监控商品（周一快照）")
            content_parts.append("| 商品 | 现价 | 影响股票 |")
            content_parts.append("|------|------|----------|")
            content_parts.extend(daily_in_weekly)

        content_parts.append("")

    content_parts.append("---")
    content_parts.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} | 监控9商品→8框架股 | 下次周报: 下周一")

    title = "⚡ 商品告警" if alerts else "📋 商品周报"
    content = "\n".join(content_parts)
    print(f"\n{'='*50}")
    print(content[:500])
    pushplus_send(title, content)
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
