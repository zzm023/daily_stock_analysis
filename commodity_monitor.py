#!/usr/bin/env python3
"""
大宗商品价格监控 v3
数据源：新浪期货API + 100ppi新闻标题匹配
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
        "level": "daily", "unit": "元/吨", "threshold": 0.03,
        "sina_futures": "LC0",
        "ppi_keyword": "碳酸锂",
    },
    "聚合MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily", "unit": "元/吨", "threshold": 0.02,
        "ppi_keyword": "聚合MDI",
    },
    "纯MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily", "unit": "元/吨", "threshold": 0.02,
        "ppi_keyword": "纯MDI",
    },
    "钛白粉(金红石型)": {
        "stocks": ["龙佰集团(002601)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
        "ppi_keyword": "钛白粉",
    },
    "蛋氨酸": {
        "stocks": ["安迪苏(600299)"],
        "level": "weekly", "unit": "元/公斤", "threshold": 0.03,
        "ppi_keyword": "蛋氨酸",
    },
    "PO42.5水泥": {
        "stocks": ["海螺水泥(600585)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
        "ppi_keyword": "水泥",
    },
    "动力煤(5500大卡)": {
        "stocks": ["海螺水泥(600585)", "兖矿能源(600188)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
        "ppi_keyword": "动力煤",
    },
    "氯化钾": {
        "stocks": ["盐湖股份(000792)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.03,
        "ppi_keyword": "氯化钾",
    },
    "EVA光伏料": {
        "stocks": ["福斯特(603806)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
        "ppi_keyword": "EVA",
    },
    "天然橡胶": {
        "stocks": ["赛轮轮胎(601058)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
        "sina_futures": "RU0",
        "ppi_keyword": "天然橡胶",
    },
}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
DATA_FILE = Path(__file__).parent / "commodity_prices.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get_sina_futures(symbol):
    """新浪期货主力合约"""
    try:
        url = f"https://hq.sinajs.cn/list={symbol}"
        resp = requests.get(url, headers={**HEADERS, "Referer": "https://finance.sina.com.cn"}, timeout=10)
        resp.encoding = "gbk"
        m = re.search(r'"([^"]*)"', resp.text)
        if not m:
            return None
        parts = m.group(1).split(",")
        if len(parts) < 4:
            return None
        price = float(parts[3]) if parts[3] else 0
        prev = float(parts[2]) if parts[2] else 0
        if price <= 0:
            return None
        change_pct = (price - prev) / prev if prev > 0 else 0
        return {"price": price, "date": str(date.today()), "change_pct": round(change_pct, 4)}
    except Exception as e:
        print(f"    [新浪期货] {symbol} 异常: {e}")
        return None


def get_100ppi_news_price(keyword):
    """从100ppi新闻搜索页面标题中提取价格"""
    try:
        # 搜索今日基准价新闻
        url = f"https://www.100ppi.com/news/?keyword={keyword}+基准价"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text

        # 匹配新闻标题中的价格，如 "8月3日生意社聚合MDI基准价为17866.67元/吨"
        patterns = [
            rf'{re.escape(keyword)}.*?基准价[为是](\d+[\.\d]*)元',
            rf'基准价[为是](\d+[\.\d]*)元.*?{re.escape(keyword)}',
            rf'{re.escape(keyword)}.*?(\d+[\.\d]*)元/吨',
            rf'生意社.*?{re.escape(keyword)}.*?(\d+[\.\d]*)元',
        ]
        for pat in patterns:
            matches = re.findall(pat, html)
            for m in matches:
                price = float(m)
                if 10 < price < 1000000:
                    return {"price": price, "date": str(date.today()), "change_pct": None}

        # 方法2：直接匹配页面中的价格信息（更宽松）
        loose_pat = r'(\d{4,6}\.\d{2})\s*元/[吨公斤]'
        matches = re.findall(loose_pat, html)
        for m in matches:
            price = float(m)
            if 1000 < price < 500000:
                # 检查关键词是否在附近
                idx = html.find(m)
                context = html[max(0,idx-200):idx+200]
                if keyword in context:
                    return {"price": price, "date": str(date.today()), "change_pct": None}

        print(f"    [100ppi搜索] 未匹配: {keyword}")
    except Exception as e:
        print(f"    [100ppi搜索] {keyword} 异常: {e}")
    return None


def get_commodity_price(name, cfg):
    # 优先期货
    if "sina_futures" in cfg:
        result = get_sina_futures(cfg["sina_futures"])
        if result:
            print(f"    [新浪期货] ✅")
            return result

    # 100ppi新闻搜索
    if "ppi_keyword" in cfg:
        result = get_100ppi_news_price(cfg["ppi_keyword"])
        if result:
            print(f"    [100ppi新闻] ✅")
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
        print(f"  [PushPlus] {'✅' if result.get('code')==200 else result}")
    except Exception as e:
        print(f"  [PushPlus] 异常: {e}")


def should_check_today(cfg):
    if cfg.get("level") == "daily":
        return True
    return datetime.now().weekday() == 0


def main():
    today = datetime.now()
    wd = ['一','二','三','四','五','六','日']
    print(f"=== 大宗商品监控 v3 | {today.strftime('%Y-%m-%d %H:%M')} 周{wd[today.weekday()]} ===")

    history = load_history()
    alerts, weekly_items = [], []
    all_data, ok, fail = {}, 0, 0

    for name, cfg in COMMODITIES.items():
        if not should_check_today(cfg):
            all_data[name] = history.get(name, {})
            continue

        print(f"\n[{name}] ...")
        result = get_commodity_price(name, cfg)

        if result is None:
            print(f"  ❌ 失败")
            fail += 1
            all_data[name] = history.get(name, {})
            continue

        ok += 1
        np_ = result["price"]
        old = history.get(name, {}).get("price")
        record = {"price": np_, "date": result["date"], "unit": cfg["unit"],
                   "stocks": ", ".join(cfg["stocks"]), "_name": name}
        all_data[name] = record
        print(f"  ✅ {np_:,.0f} {cfg['unit']}")

        if old and old > 0:
            chg = (np_ - old) / old
            record["change_pct"] = round(chg, 4)
            d = "↑" if chg>0 else "↓" if chg<0 else "→"
            print(f"     上次: {old:,.0f}  |  {d} {abs(chg)*100:.1f}%")
            if abs(chg) >= cfg["threshold"]:
                alerts.append({"name":name,"price":np_,"old_price":old,
                               "change_pct":chg,"stocks":cfg["stocks"],"unit":cfg["unit"]})
        if cfg.get("level")=="weekly" and today.weekday()==0:
            weekly_items.append(record)

    save_history(all_data)
    print(f"\n{'='*40}\n成功 {ok} / 失败 {fail}")

    if not alerts and not weekly_items:
        print("无告警无周报，不推送")
        return

    lines = []
    if alerts:
        lines.append(f"## ⚠️ 商品告警 ({len(alerts)}项)\n")
        lines.append("| 商品 | 现价 | 变动 | 影响 |")
        lines.append("|---|---|---|---|")
        for a in alerts:
            dd = "📈" if a["change_pct"]>0 else "📉"
            lines.append(f"| {a['name']} | {a['price']:,.0f} {a['unit']} | {dd} {a['change_pct']*100:+.1f}% | {', '.join(a['stocks'])} |")
        lines.append("")
    if weekly_items and today.weekday()==0:
        lines.append("## 📋 周报\n")
        lines.append("| 商品 | 现价 | 影响 |")
        lines.append("|---|---|---|")
        for it in weekly_items:
            lines.append(f"| {it.get('_name','')} | {it['price']:,.0f} {it['unit']} | {it['stocks']} |")
        daily = [f"| {n} | {d['price']:,.0f} {COMMODITIES[n]['unit']} | {d['stocks']} |"
                 for n,d in all_data.items() if COMMODITIES.get(n,{}).get('level')=='daily' and d]
        if daily:
            lines.append("\n### 每日监控快照")
            lines.append("| 商品 | 现价 | 影响 |")
            lines.append("|---|---|---|")
            lines.extend(daily)
        lines.append("")
    lines.append(f"---\n⏰ {today.strftime('%Y-%m-%d %H:%M')} | ✅{ok}/❌{fail} | 下次周报: 下周一")

    title = "⚡ 商品告警" if alerts else "📋 商品周报"
    content = "\n".join(lines)
    print(f"\n{content[:400]}...")
    pushplus_send(title, content)
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
