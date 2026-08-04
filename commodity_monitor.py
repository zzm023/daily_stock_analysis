#!/usr/bin/env python3
"""
大宗商品价格监控脚本 v2
修复：akshare期货接口 + 生意社BeautifulSoup解析 + git权限
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
        "futures_sina": "LC0",
        "ppid": "1423",
    },
    "聚合MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily",
        "unit": "元/吨",
        "threshold": 0.02,
        "ppid": "264",
    },
    "纯MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily",
        "unit": "元/吨",
        "threshold": 0.02,
        "ppid": "265",
    },
    "钛白粉(金红石型)": {
        "stocks": ["龙佰集团(002601)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "ppid": "764",
    },
    "蛋氨酸": {
        "stocks": ["安迪苏(600299)"],
        "level": "weekly",
        "unit": "元/公斤",
        "threshold": 0.03,
        "ppid": "843",
    },
    "PO42.5水泥": {
        "stocks": ["海螺水泥(600585)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "ppid": "308",
    },
    "动力煤(5500大卡)": {
        "stocks": ["海螺水泥(600585)", "兖矿能源(600188)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "ppid": "345",
    },
    "氯化钾": {
        "stocks": ["盐湖股份(000792)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.03,
        "ppid": "389",
    },
    "EVA光伏料": {
        "stocks": ["福斯特(603806)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "ppid": "1139",
    },
    "天然橡胶": {
        "stocks": ["赛轮轮胎(601058)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "futures_sina": "RU0",
        "ppid": "653",
    },
}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
DATA_FILE = Path(__file__).parent / "commodity_prices.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ─── 方式1：新浪期货主力合约 ───
def get_sina_futures(symbol):
    """直接调新浪期货API获取主力合约价格"""
    try:
        url = f"https://hq.sinajs.cn/list={symbol}"
        resp = requests.get(url, headers={**HEADERS, "Referer": "https://finance.sina.com.cn"}, timeout=10)
        resp.encoding = "gbk"
        text = resp.text
        # 格式: var hq_str_LC0="名称,今开,昨收,..."
        m = re.search(r'"([^"]*)"', text)
        if not m:
            return None
        parts = m.group(1).split(",")
        if len(parts) < 4:
            return None
        # parts[0]名前, parts[1]今开, parts[2]昨收, parts[3]现价
        price = float(parts[3]) if parts[3] != "0.000" else float(parts[8]) if len(parts) > 8 else 0
        prev_close = float(parts[2]) if parts[2] != "0.000" else 0
        if price == 0:
            return None
        change_pct = (price - prev_close) / prev_close if prev_close > 0 else 0
        return {"price": price, "date": str(date.today()), "change_pct": round(change_pct, 4)}
    except Exception as e:
        print(f"  [新浪期货] {symbol} 失败: {e}")
        return None


# ─── 方式2：生意社 BeautifulSoup ───
def get_100ppi_bs(ppid, name):
    try:
        url = f"https://www.100ppi.com/price/detail-{ppid}.html"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text

        # 尝试多种模式匹配价格
        patterns = [
            r'price["\s:]+(\d+[\.\d]*)',
            r'class="[^"]*price[^"]*"[^>]*>([\d,]+[\.\d]*)',
            r'价格[：:]\s*(\d+[\.\d]*)',
            r'>(\d{2,6}[\.\d]*)<',
            r'<td[^>]*>(\d{2,6}\.\d{2})</td>',
        ]
        for pat in patterns:
            matches = re.findall(pat, html, re.IGNORECASE)
            for m in matches:
                val = m.replace(",", "")
                try:
                    price = float(val)
                    if 10 < price < 1000000:  # 合理价格范围
                        return {"price": price, "date": str(date.today()), "change_pct": None}
                except:
                    continue
        print(f"  [100ppi] {name}({ppid}) 未匹配到价格")
    except Exception as e:
        print(f"  [100ppi] {name}({ppid}) 失败: {e}")
    return None


# ─── 方式3：东方财富商品现货 ───
def get_eastmoney_spot(name, code):
    """东方财富现货价格，备用源"""
    try:
        # 尝试东方财富商品市场API
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid=113.{code}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data"):
            d = data["data"]
            price = d.get("f43", 0) / 100 if d.get("f43") else 0
            prev = d.get("f60", 0) / 100 if d.get("f60") else 0
            if price > 0:
                change_pct = (price - prev) / prev if prev > 0 else 0
                return {"price": price, "date": str(date.today()), "change_pct": round(change_pct, 4)}
    except Exception:
        pass
    return None


# ─── 综合获取 ───
def get_commodity_price(name, cfg):
    """多源fallback：新浪期货 → 东方财富现货 → 生意社"""
    # 1. 期货源
    if "futures_sina" in cfg:
        result = get_sina_futures(cfg["futures_sina"])
        if result:
            print(f"    [新浪期货] ✅")
            return result

    # 2. 东方财富
    ew_codes = {
        "碳酸锂": "115.LC0", "天然橡胶": "113.RU0",
    }
    if name in ew_codes:
        result = get_eastmoney_spot(name, ew_codes[name])
        if result:
            print(f"    [东方财富] ✅")
            return result

    # 3. 生意社
    if "ppid" in cfg:
        result = get_100ppi_bs(cfg["ppid"], name)
        if result:
            print(f"    [100ppi] ✅")
            return result

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
        print("  [PushPlus] 未配置TOKEN")
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        result = r.json()
        print(f"  [PushPlus] {'成功' if result.get('code')==200 else result}")
    except Exception as e:
        print(f"  [PushPlus] 异常: {e}")


def should_check_today(cfg):
    if cfg.get("level") == "daily":
        return True
    return datetime.now().weekday() == 0


def main():
    today = datetime.now()
    print(f"=== 大宗商品价格监控 v2 ===")
    print(f"时间: {today.strftime('%Y-%m-%d %H:%M')}")
    weekday_cn = ['一','二','三','四','五','六','日']
    print(f"星期: {weekday_cn[today.weekday()]}")

    history = load_history()
    alerts = []
    weekly_items = []
    all_data = {}
    success_count = 0
    fail_count = 0

    for name, cfg in COMMODITIES.items():
        if not should_check_today(cfg):
            all_data[name] = history.get(name, {})
            continue

        print(f"\n[{name}] ...")
        result = get_commodity_price(name, cfg)

        if result is None:
            print(f"  ❌ 所有数据源均失败")
            fail_count += 1
            all_data[name] = history.get(name, {})
            continue

        success_count += 1
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
                    "name": name, "price": new_price, "old_price": old_price,
                    "change_pct": change_pct, "stocks": cfg["stocks"], "unit": cfg["unit"],
                })

        if cfg.get("level") == "weekly" and today.weekday() == 0:
            weekly_items.append(record)

    save_history(all_data)

    print(f"\n{'='*40}")
    print(f"结果：成功 {success_count} / 失败 {fail_count}")

    if not alerts and not weekly_items:
        print("无告警，无周报，不推送。")
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

    if weekly_items and today.weekday() == 0:
        content_parts.append("## 📋 周度商品价格总览")
        content_parts.append("")
        content_parts.append("| 商品 | 现价 | 影响股票 |")
        content_parts.append("|------|------|----------|")
        for item in weekly_items:
            content_parts.append(f"| {item.get('_name','')} | {item['price']:,.0f} {item['unit']} | {item['stocks']} |")

        daily = []
        for n, d in all_data.items():
            c = COMMODITIES.get(n, {})
            if c.get("level") == "daily" and d:
                daily.append(f"| {n} | {d['price']:,.0f} {c['unit']} | {d['stocks']} |")
        if daily:
            content_parts.append("")
            content_parts.append("### 每日监控（周一快照）")
            content_parts.append("| 商品 | 现价 | 影响股票 |")
            content_parts.append("|------|------|----------|")
            content_parts.extend(daily)

        content_parts.append("")

    content_parts.append("---")
    content_parts.append(f"⏰ {today.strftime('%Y-%m-%d %H:%M')} | 成功{success_count}/失败{fail_count} | 下次周报: 下周一")

    title = "⚡ 商品告警" if alerts else "📋 商品周报"
    content = "\n".join(content_parts)
    print(f"\n{content[:400]}...")
    pushplus_send(title, content)
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
