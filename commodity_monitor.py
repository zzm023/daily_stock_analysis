#!/usr/bin/env python3
"""
大宗商品价格监控 v5 — 修正akshare函数名 + 自适应列名
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


def get_price_via_futures(code):
    """用akshare期货接口获取主力合约收盘价"""
    try:
        import akshare as ak
        # 尝试多个函数名（不同版本兼容）
        for func_name in ["futures_zh_daily_sina", "futures_zh_daily"]:
            try:
                func = getattr(ak, func_name)
                df = func(symbol=code)
                if df is None or len(df) == 0:
                    continue
                # 自适应列名
                cols = [c.lower() for c in df.columns]
                original_cols = list(df.columns)
                close_col = None
                date_col = None
                for orig, low in zip(original_cols, cols):
                    if low in ("close", "收盘价", "收盘", "f_close"):
                        close_col = orig
                    if low in ("date", "日期", "trade_date", "datetime"):
                        date_col = orig
                if close_col is None:
                    # 模糊匹配：含"收"的列
                    for orig in original_cols:
                        if "收" in orig:
                            close_col = orig
                            break
                if close_col:
                    latest = df.iloc[-1]
                    close_val = float(latest[close_col])
                    date_val = str(latest[date_col])[:10] if date_col else str(date.today())
                    if close_val > 0:
                        return {"price": close_val, "date": date_val, "change_pct": None}
            except Exception:
                continue
    except Exception as e:
        print(f"    [akshare] {code} 异常: {e}")
    return None


def get_price_via_eastmoney(code):
    """东方财富主力合约"""
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {"secid": f"113.{code}", "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60"}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json().get("data", {})
        price = data.get("f43", 0) / 100 if data.get("f43") else 0
        if price > 0:
            prev = data.get("f60", 0) / 100 if data.get("f60") else 0
            chg = (price - prev) / prev if prev > 0 else 0
            return {"price": price, "date": str(date.today()), "change_pct": round(chg, 4)}
    except Exception:
        pass
    return None


def get_commodity_price(name, cfg):
    if "futures_code" in cfg:
        code = cfg["futures_code"]
        # 1. akshare
        result = get_price_via_futures(code)
        if result:
            print(f"    [akshare] ✅")
            return result
        # 2. 东方财富
        result = get_price_via_eastmoney(code)
        if result:
            print(f"    [东方财富] ✅")
            return result
    # 现货品种：无API
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
    return cfg.get("level") == "daily" or datetime.now().weekday() == 0


def main():
    today = datetime.now()
    wd = ['一','二','三','四','五','六','日']
    print(f"=== 大宗商品监控 v5 | {today.strftime('%Y-%m-%d %H:%M')} 周{wd[today.weekday()]} ===")

    history = load_history()
    alerts, weekly_items = [], []
    all_data, ok, fail, nosrc = {}, 0, 0, 0

    for name, cfg in COMMODITIES.items():
        if not should_check_today(cfg):
            all_data[name] = history.get(name, {})
            continue
        print(f"\n[{name}] ...")

        if "futures_code" not in cfg:
            print(f"  ⚠️ 现货品种，无API数据源")
            nosrc += 1
            all_data[name] = history.get(name, {})
            continue

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
    print(f"\n{'='*40}\n✅{ok} ❌{fail} ⚠️无源{nosrc}")

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
        lines.append("")
    lines.append(f"---\n⏰ {today.strftime('%Y-%m-%d %H:%M')} | ✅{ok} ❌{fail} ⚠️{nosrc}")

    pushplus_send("⚡ 商品告警" if alerts else "📋 商品周报", "\n".join(lines))
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
