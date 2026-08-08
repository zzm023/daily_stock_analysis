#!/usr/bin/env python3
"""
大宗商品价格监控 v8
数据源：akshare期货 + 100ppi品种子站新闻列表
每周一推送完整报告，每日仍有告警实时推送
"""

import requests
import json
import os
import re
from datetime import datetime, date
from pathlib import Path

COMMODITIES = {
    "碳酸锂": {
        "stocks": ["盐湖股份(000792)"], "level": "daily",
        "unit": "元/吨", "threshold": 0.03,
        "ak_futures": "LC0",
    },
    "聚合MDI": {
        "stocks": ["万华化学(600309)"], "level": "daily",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "mdi.100ppi.com",
    },
    "纯MDI": {
        "stocks": ["万华化学(600309)"], "level": "daily",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "www.100ppi.com",
        "title_filter": "纯MDI",
    },
    "钛白粉(金红石型)": {
        "stocks": ["龙佰集团(002601)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "tio2.100ppi.com",
    },
    "蛋氨酸": {
        "stocks": ["安迪苏(600299)"], "level": "weekly",
        "unit": "元/公斤", "threshold": 0.03,
        "ppi_sub": "met.100ppi.com",
    },
    "PO42.5水泥": {
        "stocks": ["海螺水泥(600585)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "sn.100ppi.com",
    },
    "动力煤(5500大卡)": {
        "stocks": ["海螺水泥(600585)", "兖矿能源(600188)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "coal.100ppi.com",
    },
    "氯化钾": {
        "stocks": ["盐湖股份(000792)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.03,
        "ppi_sub": "kcl.100ppi.com",
    },
    "EVA光伏料": {
        "stocks": ["福斯特(603806)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "eva.100ppi.com",
    },
    "天然橡胶": {
        "stocks": ["赛轮轮胎(601058)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.02,
        "ak_futures": "RU0",
    },
}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
DATA_FILE = Path(__file__).parent / "commodity_prices.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get_akshare_futures(code):
    try:
        import akshare as ak
        for func_name in ["futures_zh_daily_sina", "futures_zh_daily"]:
            try:
                func = getattr(ak, func_name)
                df = func(symbol=code)
                if df is None or len(df) == 0:
                    continue
                for orig in df.columns:
                    if "收" in orig or orig.lower() in ("close", "f_close"):
                        val = float(df.iloc[-1][orig])
                        if val > 0:
                            return {"price": val, "date": str(date.today()), "change_pct": None}
                row = df.iloc[-1]
                for orig in df.columns:
                    try:
                        v = float(row[orig])
                        if 10 < v < 10000000:
                            return {"price": v, "date": str(date.today()), "change_pct": None}
                    except:
                        continue
            except Exception:
                continue
    except Exception as e:
        print(f"    [akshare] {code}: {e}")
    return None


def get_ppi_sub_price(subdomain, keyword, title_filter=None):
    try:
        url = f"https://{subdomain}/news/list---1.html"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        html = resp.text

        pat = rf'基准价[为是](\d+[\.\d]*)元'
        matches = re.findall(pat, html)
        if matches:
            for m in matches:
                p = float(m)
                if 100 < p < 10000000:
                    if title_filter:
                        idx = html.find(m)
                        ctx = html[max(0,idx-500):idx+100]
                        if title_filter not in ctx:
                            continue
                    return {"price": p, "date": str(date.today()), "change_pct": None}

        pat2 = r'(\d{4,7}\.\d{2})\s*元/[吨公斤]'
        matches2 = re.findall(pat2, html)
        for m in matches2:
            p = float(m)
            if 100 < p < 500000:
                idx = html.find(m)
                ctx = html[max(0,idx-300):idx+100]
                if keyword in ctx or "基准价" in ctx or "报价" in ctx:
                    if title_filter and title_filter not in ctx:
                        continue
                    return {"price": p, "date": str(date.today()), "change_pct": None}

        print(f"    [子站] {subdomain} 页面已获取但未匹配价格")
    except Exception as e:
        print(f"    [子站] {subdomain} 异常: {e}")
    return None


def get_commodity_price(name, cfg):
    if "ak_futures" in cfg:
        result = get_akshare_futures(cfg["ak_futures"])
        if result:
            print(f"    [akshare期货] ✅")
            return result
    if "ppi_sub" in cfg:
        kw = name.split("(")[0]
        tf = cfg.get("title_filter")
        result = get_ppi_sub_price(cfg["ppi_sub"], kw, tf)
        if result:
            print(f"    [100ppi子站] ✅")
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
        print("  [PushPlus] 未配置TOKEN"); return
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
    is_monday = today.weekday() == 0
    print(f"=== 大宗商品监控 v8 | {today.strftime('%Y-%m-%d %H:%M')} 周{wd[today.weekday()]} ===")

    history = load_history()
    alerts, all_rows = [], []
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
        chg = None
        if old and old > 0:
            chg = round((np_ - old) / old, 4)
            d = "↑" if chg>0 else "↓" if chg<0 else "→"
            print(f"  ✅ {np_:,.0f} {cfg['unit']} | {d} {abs(chg)*100:.1f}%")
            if abs(chg) >= cfg["threshold"]:
                alerts.append({"name":name,"price":np_,"old_price":old,"change_pct":chg,
                               "stocks":cfg["stocks"],"unit":cfg["unit"]})
        else:
            print(f"  ✅ {np_:,.0f} {cfg['unit']}（首次）")

        record = {"price": np_, "date": result["date"], "unit": cfg["unit"],
                   "stocks": ", ".join(cfg["stocks"]), "_name": name,
                   "change_pct": chg}
        all_data[name] = record
        all_rows.append((name, np_, cfg["unit"], ", ".join(cfg["stocks"]), chg, cfg["threshold"]))

    save_history(all_data)
    print(f"\n{'='*40}\n✅{ok} ❌{fail}")

    # ── 生成推送内容 ──
    lines = [f"## 📦 大宗商品 — {today:%Y.%m.%d}", "",
             f"> {'周报' if is_monday else '日报'} ｜ 监控10品种→8框架股 ｜ {today:%m-%d %H:%M}", ""]

    # 告警（如有）
    if alerts:
        lines.append("### ⚠️ 告警")
        for a in alerts:
            dd = "📈" if a["change_pct"]>0 else "📉"
            lines.append(f"**{a['name']}** {dd} {a['change_pct']*100:+.1f}%")
            lines.append(f"> 现价 {a['price']:,.0f} {a['unit']}（上次{a['old_price']:,.0f}）")
            lines.append(f"> 影响：{', '.join(a['stocks'])}")
            lines.append("")
        lines.append("")

    # 全品种价格表
    lines.append("### 📋 全部品种")
    lines.append("")
    for name, price, unit, stocks, chg, threshold in all_rows:
        if chg is not None:
            arrow = "↑" if chg > 0 else "↓" if chg < 0 else "→"
            flag = "🔴" if abs(chg) >= threshold else "⚪"
            change_str = f"{flag} {arrow} {abs(chg)*100:.1f}%"
        else:
            change_str = "🆕 首次"
        lines.append(f"**{name}** {price:,.0f} {unit} | {change_str}")
        lines.append(f"> {stocks}")
        lines.append("")

    lines.append(f"---")
    lines.append(f"✅{ok} ❌{fail} | {today:%Y-%m-%d %H:%M}")

    title = f"⚡ 商品告警({len(alerts)}项)" if alerts else ("📦 商品周报" if is_monday else "📦 商品日报")
    pushplus_send(title, "\n".join(lines))

    print("\n✅ 完成")


if __name__ == "__main__":
    main()
