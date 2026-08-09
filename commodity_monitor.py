#!/usr/bin/env python3
"""
大宗商品价格监控 v9
联动触发清单：异动时标注是否影响触发清单股票
数据源：akshare期货 + 100ppi品种子站 ｜ 自动提交状态文件
每日推送，所有品种显示
"""
import requests
import json
import os
import re
import subprocess
from datetime import datetime, date
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
DATA_FILE = Path(__file__).parent / "commodity_prices.json"

COMMODITY_STOCK_MAP = {
    "碳酸锂":    ["000792"],
    "聚合MDI":   ["600309"],
    "钛白粉":    ["002601"],
    "蛋氨酸":    ["600299"],
    "水泥":      ["600585"],
    "动力煤":    ["600585", "600188"],
    "氯化钾":    ["000792"],
    "EVA光伏料": ["603806"],
    "天然橡胶":  ["601058"],
}

STOCK_NAMES = {
    "000792":"盐湖股份","600309":"万华化学","002601":"龙佰集团",
    "600299":"安迪苏","600585":"海螺水泥","600188":"兖矿能源",
    "603806":"福斯特","601058":"赛轮轮胎",
}

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
    "钛白粉": {
        "stocks": ["龙佰集团(002601)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "tio2.100ppi.com",
    },
    "蛋氨酸": {
        "stocks": ["安迪苏(600299)"], "level": "weekly",
        "unit": "元/公斤", "threshold": 0.03,
        "ppi_sub": "met.100ppi.com",
    },
    "水泥": {
        "stocks": ["海螺水泥(600585)"], "level": "weekly",
        "unit": "元/吨", "threshold": 0.02,
        "ppi_sub": "sn.100ppi.com",
    },
    "动力煤": {
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger": {}, "holdings": {}}


def save_state(s):
    s["meta"] = s.get("meta", {})
    s["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def git_commit_state():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", "framework_state.json"], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "[auto] 更新商品事件"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("[GIT] framework_state.json 已提交")
    except Exception as e:
        print(f"[GIT] 提交失败: {e}")


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


def get_ppi_sub_price(subdomain, keyword):
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
                    return {"price": p, "date": str(date.today()), "change_pct": None}
        pat2 = r'(\d{4,7}\.\d{2})\s*元/[吨公斤]'
        matches2 = re.findall(pat2, html)
        for m in matches2:
            p = float(m)
            if 100 < p < 500000:
                idx = html.find(m)
                ctx = html[max(0,idx-300):idx+100]
                if keyword in ctx or "基准价" in ctx or "报价" in ctx:
                    return {"price": p, "date": str(date.today()), "change_pct": None}
        print(f"    [子站] {subdomain} 未匹配价格")
    except Exception as e:
        print(f"    [子站] {subdomain} 异常: {e}")
    return None


def get_commodity_price(name, cfg):
    if "ak_futures" in cfg:
        result = get_akshare_futures(cfg["ak_futures"])
        if result:
            print(f"    [akshare] ✅")
            return result
    if "ppi_sub" in cfg:
        kw = name.split("(")[0]
        result = get_ppi_sub_price(cfg["ppi_sub"], kw)
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


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"  [PushPlus] {'✅' if r.json().get('code')==200 else r.json()}")
    except Exception as e:
        print(f"  [PushPlus] {e}")


def should_check_today(cfg):
    if cfg.get("level") == "daily":
        return True
    return datetime.now().weekday() == 0


def main():
    today = datetime.now()
    wd = ['一','二','三','四','五','六','日']
    is_monday = today.weekday() == 0
    print(f"=== 大宗商品监控 v9 | {today:%Y-%m-%d %H:%M} 周{wd[today.weekday()]} ===")

    state = load_state()
    trigger = state.get("trigger", {})

    trigger_codes = {c for c, v in trigger.items() if v.get("status") in ("已触发","接近")}
    print(f"  触发清单: {len(trigger_codes)} 只 → {[STOCK_NAMES.get(c,c) for c in trigger_codes]}")

    history = load_history()
    alerts, all_rows = [], []
    all_data, ok, fail = {}, 0, 0
    commodity_events = []

    for name, cfg in COMMODITIES.items():
        if not should_check_today(cfg):
            cached = history.get(name, {})
            if cached:
                all_data[name] = cached
                all_rows.append((name, cached.get("price",0), cfg["unit"],
                                 ", ".join(cfg["stocks"]), cached.get("change_pct"), cfg["threshold"]))
            continue

        print(f"\n[{name}] ...")
        result = get_commodity_price(name, cfg)
        if result is None:
            print(f"  ❌ 失败")
            fail += 1
            cached = history.get(name, {})
            all_data[name] = cached
            if cached:
                all_rows.append((name, cached.get("price",0), cfg["unit"],
                                 ", ".join(cfg["stocks"]), cached.get("change_pct"), cfg["threshold"]))
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
                affected_codes = COMMODITY_STOCK_MAP.get(name, [])
                in_trigger = [c for c in affected_codes if c in trigger_codes]
                alerts.append({
                    "name":name,"price":np_,"old_price":old,"change_pct":chg,
                    "stocks":cfg["stocks"],"unit":cfg["unit"],
                    "in_trigger": in_trigger
                })
                commodity_events.append({
                    "commodity": name,
                    "price": np_,
                    "old_price": old,
                    "change_pct": chg,
                    "stocks": affected_codes,
                    "in_trigger": in_trigger,
                    "date": str(date.today())
                })
        else:
            print(f"  ✅ {np_:,.0f} {cfg['unit']}（首次）")

        record = {"price": np_, "date": result["date"], "unit": cfg["unit"],
                   "stocks": ", ".join(cfg["stocks"]), "_name": name,
                   "change_pct": chg}
        all_data[name] = record
        all_rows.append((name, np_, cfg["unit"], ", ".join(cfg["stocks"]), chg, cfg["threshold"]))

    state["commodity_events"] = commodity_events
    save_state(state)
    save_history(all_data)

    print(f"\n{'='*40}\n✅{ok} ❌{fail}")

    lines = [f"## 📦 大宗商品 — {today:%Y.%m.%d}", "",
             f"> {'周报' if is_monday else '日报'} ｜ 监控9品种 ｜ {today:%m-%d %H:%M}", ""]

    if alerts:
        lines.append("### ⚠️ 异动告警")
        lines.append("")
        for a in alerts:
            dd = "📈" if a["change_pct"]>0 else "📉"
            trigger_tag = "🔴 命中触发清单" if a["in_trigger"] else "⚪ 不在清单"
            lines.append(f"**{a['name']}** {dd} {a['change_pct']*100:+.1f}% {trigger_tag}")
            lines.append(f"> 现价 {a['price']:,.0f} {a['unit']}（上次{a['old_price']:,.0f}）")
            stock_names = [f"{STOCK_NAMES.get(c,c)}({c})" for c in a.get("in_trigger",[])]
            if stock_names:
                lines.append(f"> ⚠️ 影响触发清单：{', '.join(stock_names)}")
            lines.append("")
        lines.append("")

    lines.append("### 📋 全部品种")
    lines.append("")
    for name, price, unit, stocks, chg, threshold in all_rows:
        affected = COMMODITY_STOCK_MAP.get(name, [])
        hit_trigger = [c for c in affected if c in trigger_codes]
        tag = " 🔴清单" if hit_trigger else ""

        if chg is not None:
            arrow = "↑" if chg > 0 else "↓" if chg < 0 else "→"
            flag = "🔴" if abs(chg) >= threshold else "⚪"
            change_str = f"{flag} {arrow} {abs(chg)*100:.1f}%"
        else:
            change_str = "🆕"
        lines.append(f"**{name}**{tag} {price:,.0f} {unit} | {change_str}")
        lines.append(f"> {stocks}")
        lines.append("")

    lines.append(f"---")
    lines.append(f"✅{ok} ❌{fail} | {today:%Y-%m-%d %H:%M}")

    title = f"⚡ 商品异动({len(alerts)}项)" if alerts else ("📦 商品周报" if is_monday else "📦 商品日报")
    push(title, "\n".join(lines))

    git_commit_state()
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
