#!/usr/bin/env python3
"""股息率周报：自动拉分红（÷10校正）+ 现价（新浪）
每周一 08:00 CST
"""
import requests
import re
import os
from datetime import datetime, timedelta, date as date_type

DIV = {
    "600036": {"name": "招商银行", "dps": 2.10, "anchor": 6.0},
    "601601": {"name": "中国太保", "dps": 1.02, "anchor": 3.4},
    "600018": {"name": "上港集团", "dps": 0.18, "anchor": 3.8},
    "601816": {"name": "京沪高铁", "dps": 0.12, "anchor": 2.5},
    "600900": {"name": "长江电力", "dps": 0.85, "anchor": 4.0},
    "600941": {"name": "中国移动", "dps": 5.35, "anchor": 5.5},
    "600406": {"name": "国电南瑞", "dps": 0.25, "anchor": 1.3},
    "600598": {"name": "北大荒",   "dps": 0.44, "anchor": 3.8},
    "603568": {"name": "伟明环保", "dps": 0.50, "anchor": 3.4},
    "600007": {"name": "中国国贸", "dps": 0.98, "anchor": 5.6},
    "000429": {"name": "粤高速A",  "dps": 0.61, "anchor": 5.8},
    "000895": {"name": "双汇发展", "dps": 1.32, "anchor": 6.0},
    "000848": {"name": "承德露露", "dps": 0.44, "anchor": 5.5},
}

CUTOFF = (datetime.now() - timedelta(days=365)).date()


def parse_date(v):
    """兼容 datetime / date / NaT / NaN / str"""
    if v is None:
        return None
    # NaT / NaN: self != self
    try:
        if v != v:
            return None
    except TypeError:
        return None
    # datetime or date
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date_type):
        return v
    # string
    s = str(v).strip()[:19]
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_dps(code):
    """akshare拉近18个月分红（派息÷10=每股）"""
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
             f"> DPS：12M实派 ｜ 现价：新浪 ｜ {now:%m-%d %H:%M}", "",
             "| 股票 | 现价 | DPS | 股息率 | 锚定 | 距锚定 |",
             "|------|------|-----|--------|------|--------|"]

    for name, code, price, dps, src, yld, anchor, gap in rows:
        ps = f"{price:.2f}" if price else "-"
        dp = f"{dps:.3f}" if dps else "-"
        ys = f"{yld:.2f}%" if yld else "-"
        gs = f"🟢 差{gap:+.1f}pp" if gap > 0 else (f"● 超额{-gap:.1f}pp" if gap < 0 else "🎯 持平")
        lines.append(f"| {name} | {ps} | {dp} | {ys} | {anchor:.1f}% | {gs} |")

    triggered = [(n, g, y) for n, _, _, _, _, y, _, g in rows if g <= 0]
    close = [(n, g, y) for n, _, _, _, _, y, _, g in rows if g > 0 and g <= 0.5]
    if triggered:
        lines.append(""); lines.append("### 🔴 已触发")
        for n, g, y in triggered:
            lines.append(f"- {n}：{y:.2f}%（超额{-g:.1f}pp）")
    if close:
        lines.append(""); lines.append("### 🟡 接近触发")
        for n, g, y in close:
            lines.append(f"- {n}：{y:.2f}%，差{g:.1f}pp")

    push(f"💰 股息率周报 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(rows)} 只")


if __name__ == "__main__":
    main()
