#!/usr/bin/env python3
"""股息率周报：自动拉分红（÷10校正）+ 现价（新浪）
每周一 08:00 CST
"""
import requests
import re
import os
from datetime import datetime, timedelta, date as date_type

DIV = {
    "600036": {"name": "招商银行", "dps": 2.02, "anchor": 6.0},
    "601601": {"name": "中国太保", "dps": 1.15, "anchor": 3.4},
    "600018": {"name": "上港集团", "dps": 0.145, "anchor": 4.5},
    "601816": {"name": "京沪高铁", "dps": 0.095, "anchor": 3.0},
    "600900": {"name": "长江电力", "dps": 0.79, "anchor": 4.5},
    "600941": {"name": "中国移动", "dps": 4.70, "anchor": 5.5},
    "600406": {"name": "国电南瑞", "dps": 0.475, "anchor": 3.0},
    "600598": {"name": "北大荒",   "dps": 0.55, "anchor": 3.8},
    "603568": {"name": "伟明环保", "dps": 0.60, "anchor": 3.4},
    "600007": {"name": "中国国贸", "dps": 1.07, "anchor": 6.5},
    "000429": {"name": "粤高速A",  "dps": 0.604, "anchor": 5.8},
    "002027": {"name": "分众传媒", "dps": 0.19,  "anchor": 3.5},
}

CUTOFF = (datetime.now() - timedelta(days=365)).date()


def parse_date(v):
    if v is None:
        return None
    try:
        if v != v:
            return None
    except TypeError:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date_type):
        return v
    s = str(v).strip()[:19]
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_dps(code):
    try:
        import akshare as ak
        df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
        if df is None or df.empty:
            return None, "空"

        total, found = 0.0, 0
        for _, r in df.iterrows():
            result = (parse_date(r.get("除权除息日")) or
                      parse_date(r.get("股权登记日")) or
                      parse_date(r.get("公告日期")))
            if result is None:
                continue
            if result >= CUTOFF:
                try:
                    val = float(r.get("派息", 0) or 0)
                    total += val / 10.0
                    found += 1
                except (ValueError, TypeError):
                    pass

        if found > 0 and total > 0:
            return round(total, 3), f"12M({found}条)"
        return None, f"12M无(共{len(df)}条)"
    except Exception as e:
        return None, str(e)[:60]


def fetch_price(code):
    prefix = "sh" if code.startswith("6") else "sz"
    for attempt in range(3):
        try:
            r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                             headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
            r.encoding = "gbk"
            m = re.search(r'="(.+?)"', r.text)
            if m:
                price = float(m.group(1).split(",")[3])
                if price > 0:
                    return price
        except Exception:
            if attempt < 2:
                import time; time.sleep(2)
    return 0


def push(title, content):
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] 无TOKEN"); return
    payload = {"token": token, "title": title, "content": content, "template": "markdown"}
    if topic:
        payload["topic"] = topic
    r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")


def main():
    now = datetime.now()
    print(f"[START] 股息率周报 {now:%Y-%m-%d %H:%M}")

    rows = []
    for code, v in DIV.items():
        dps, src = fetch_dps(code)
        if code == "002027":
            dps = v["dps"]
            src = "手动校正"
        if code == "600036":
            dps = v["dps"]
            src = "手动校正"
        if code == "600036" and dps is not None:
            print(f"  [OK] 招商银行DPS={dps} [{src}]")
        if dps is None:
            dps = v["dps"]
            src = f"兜底({src})"
        price = fetch_price(code)
        yld = (dps / price * 100) if price > 0 else 0
        gap = v["anchor"] - yld
        rows.append((v["name"], code, price, dps, src, yld, v["anchor"], gap))
        print(f"  {v['name']}: DPS={dps:.3f}[{src}] 价={price:.2f} 息率={yld:.2f}%")

    rows.sort(key=lambda x: -x[5])
    lines = [f"## 💰 股息率周报 — {now:%Y.%m.%d}", "",
             f"> DPS：12M实派 ｜ 现价：新浪 ｜ {now:%m-%d %H:%M}", ""]

    for name, code, price, dps, src, yld, anchor, gap in rows:
        trigger_price = round(dps / anchor * 100, 2) if dps and anchor else 0
        diff = trigger_price - price
        if gap < 0:
            status = f"🔴 已触发（超{-gap:.1f}pp）"
        elif gap == 0:
            status = "🎯 持平"
        else:
            status = f"🟢 差{diff:+.2f}元"
        lines.append(f"**{name}**")
        lines.append(f"现价 {price:.2f} → 触发价 {trigger_price:.2f} | 股息率 {yld:.2f}% | 锚定 {anchor:.1f}% | {status}")
        lines.append("")

    triggered = [(n, g, y) for n, _, _, _, _, y, _, g in rows if g <= 0]
    close = [(n, g, y) for n, _, _, _, _, y, _, g in rows if g > 0 and g <= 0.5]
    if triggered:
        lines.append("### 🔴 已触发")
        for n, g, y in triggered:
            lines.append(f"- {n}：{y:.2f}%（超额{-g:.1f}pp）")
    if close:
        lines.append("### 🟡 接近触发")
        for n, g, y in close:
            lines.append(f"- {n}：{y:.2f}%，差{g:.1f}pp")

    push(f"💰 股息率周报 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(rows)} 只")


if __name__ == "__main__":
    main()
