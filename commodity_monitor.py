#!/usr/bin/env python3
"""
大宗商品价格监控 v6
数据源：akshare期货 + 100ppi品种子站新闻列表
"""

import requests
import json
import os
import re
from datetime import datetime, date
from pathlib import Path

# 品种配置：期货用akshare，现货用100ppi子站
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
        "ppi_sub": "mdi.100ppi.com",
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
                # 最后尝试：取最后一行的数值列
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


def get_ppi_sub_price(subdomain, keyword):
    """从100ppi品种子站新闻列表提取基准价"""
    try:
        url = f"https://{subdomain}/news/list---1.html"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        html = resp.text

        # 匹配新闻标题中的基准价
        # 格式: "X月X日生意社XXX基准价为XXXXX.XX元/吨"
        pat = rf'基准价[为是](\d+[\.\d]*)元'
        matches = re.findall(pat, html)
        if matches:
            for m in matches:
                p = float(m)
                if 100 < p < 10000000:
                    return {"price": p, "date": str(date.today()), "change_pct": None}

        # 更宽松匹配：任何价格格式
        pat2 = r'(\d{4,7}\.\d{2})\s*元/[吨公斤]'
        matches2 = re.findall(pat2, html)
        for m in matches2:
            p = float(m)
            if 100 < p < 500000:
                idx = html.find(m)
                ctx = html[max(0,idx-300):idx+100]
                if keyword in ctx or "基准价" in ctx or "报价" in ctx:
                    return {"price": p, "date": str(date.today()), "change_pct": None}

        print(f"    [子站] {subdomain} 页面已获取但未匹配价格")
        # 调试：打印页面标题
        title_m = re.search(r'<title>([^<]+)</title>', html)
        if title_m:
            print(f"    页面标题: {title_m.group(1)[:100]}")
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
        kw = name.split("(")[0]  # 去掉括号里的规格
        result = get_ppi_sub_price(cfg["ppi_sub"], kw)
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
    print(f"=== 大宗商品监控 v6 | {today.strftime('%Y-%m-%d %H:%M')} 周{wd[today.weekday()]} ===")

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
                alerts.append({"name":name,"price":np_,"old_price":old,"change_pct":chg,
                               "stocks":cfg["stocks"],"unit":cfg["unit"]})
        if cfg.get("level")=="weekly" and today.weekday()==0:
            weekly_items.append(record)

    save_history(all_data)
    print(f"\n{'='*40}\n✅{ok} ❌{fail}")

    if alerts or (weekly_items and today.weekday()==0):
        lines = []
        if alerts:
            lines.append(f"## ⚠️ 告警 ({len(alerts)}项)")
            lines.append("")
            for a in alerts:
                dd = "📈" if a["change_pct"]>0 else "📉"
                lines.append(f"**{a['name']}** {dd} {a['change_pct']*100:+.1f}%")
                lines.append(f"> 现价 {a['price']:,.0f} {a['unit']}")
                lines.append(f"> 影响：{', '.join(a['stocks'])}")
                lines.append("")
        if weekly_items and today.weekday()==0:
            lines.append("## 📋 周报")
            lines.append("")
            for it in weekly_items:
                lines.append(f"**{it.get('_name','')}** {it['price']:,.0f} {it.get('unit','')}")
                lines.append(f"> 影响：{it['stocks']}")
                lines.append("")
        lines.append(f"---\n{today.strftime('%Y-%m-%d %H:%M')} | ✅{ok} ❌{fail}")
        pushplus_send("⚡ 告警" if alerts else "📋 周报", "\n".join(lines))
    else:
        print("无告警无周报")

    print("\n✅ 完成")


if __name__ == "__main__":
    main()
