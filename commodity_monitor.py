#!/usr/bin/env python3
"""
大宗商品价格监控 v4 — 全akshare方案
使用东方财富数据源，避免新浪/100ppi IP封禁
"""

import requests
import json
import os
from datetime import datetime, date
from pathlib import Path

COMMODITIES = {
    "碳酸锂": {
        "stocks": ["盐湖股份(000792)"],
        "level": "daily", "unit": "元/吨", "threshold": 0.03,
        "futures_code": "LC0",
    },
    "聚合MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily", "unit": "元/吨", "threshold": 0.02,
    },
    "纯MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily", "unit": "元/吨", "threshold": 0.02,
    },
    "钛白粉(金红石型)": {
        "stocks": ["龙佰集团(002601)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
    },
    "蛋氨酸": {
        "stocks": ["安迪苏(600299)"],
        "level": "weekly", "unit": "元/公斤", "threshold": 0.03,
    },
    "PO42.5水泥": {
        "stocks": ["海螺水泥(600585)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
    },
    "动力煤(5500大卡)": {
        "stocks": ["海螺水泥(600585)", "兖矿能源(600188)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
    },
    "氯化钾": {
        "stocks": ["盐湖股份(000792)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.03,
    },
    "EVA光伏料": {
        "stocks": ["福斯特(603806)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
    },
    "天然橡胶": {
        "stocks": ["赛轮轮胎(601058)"],
        "level": "weekly", "unit": "元/吨", "threshold": 0.02,
        "futures_code": "RU0",
    },
}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
DATA_FILE = Path(__file__).parent / "commodity_prices.json"


def get_price_via_akshare(name, cfg):
    """使用akshare内置函数获取价格"""
    try:
        import akshare as ak

        # 方式1：通过期货日线获取（有futures_code的品种）
        if "futures_code" in cfg:
            try:
                df = ak.futures_zh_daily_sina(symbol=cfg["futures_code"])
                if df is not None and len(df) > 0:
                    latest = df.iloc[-1]
                    close = float(latest["收盘价"])
                    return {"price": close, "date": str(latest["日期"]), "change_pct": None}
            except Exception as e:
                print(f"    [akshare futures_zh] {cfg['futures_code']} 失败: {e}")

        # 方式2：尝试期货现货价格函数
        try:
            today_str = date.today().strftime("%Y%m%d")
            df = ak.futures_spot_price(symbol=name, date=today_str)
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    spot_price = row.get("现货价格") or row.get("spot_price")
                    if spot_price and float(spot_price) > 0:
                        return {"price": float(spot_price), "date": today_str, "change_pct": None}
        except Exception:
            pass

    except Exception as e:
        print(f"    [akshare] 异常: {e}")
    return None


def get_price_via_eastmoney(symbol):
    """东方财富主力合约行情 — 救急备用"""
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": f"113.{symbol}",
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170",
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json().get("data", {})
        price = data.get("f43", 0) / 100 if data.get("f43") else 0
        if price > 0:
            return {"price": price, "date": str(date.today()), "change_pct": None}
    except Exception:
        pass
    return None


def get_commodity_price(name, cfg):
    # 1. akshare主方案
    result = get_price_via_akshare(name, cfg)
    if result:
        print(f"    [akshare] ✅")
        return result

    # 2. 东方财富备用
    if "futures_code" in cfg:
        result = get_price_via_eastmoney(cfg["futures_code"])
        if result:
            print(f"    [东方财富] ✅")
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
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"  [PushPlus] {'✅' if r.json().get('code')==200 else r.json()}")
    except Exception as e:
        print(f"  [PushPlus] 异常: {e}")


def should_check_today(cfg):
    if cfg.get("level") == "daily":
        return True
    return datetime.now().weekday() == 0


def main():
    today = datetime.now()
    wd = ['一','二','三','四','五','六','日']
    print(f"=== 大宗商品监控 v4 | {today.strftime('%Y-%m-%d %H:%M')} 周{wd[today.weekday()]} ===")

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
            lines.append("\n### 每日快照")
            lines.append("| 商品 | 现价 | 影响 |")
            lines.append("|---|---|---|")
            lines.extend(daily)
        lines.append("")
    lines.append(f"---\n⏰ {today.strftime('%Y-%m-%d %H:%M')} | ✅{ok}/❌{fail}")

    title = "⚡ 商品告警" if alerts else "📋 商品周报"
    pushplus_send(title, "\n".join(lines))
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
