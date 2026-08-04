#!/usr/bin/env python3
"""股息率周报：自动拉12个月分红DPS + 现价
每周一 08:00 CST
"""
import requests
import os
import re
from datetime import datetime, timedelta

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

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_dps(code):
    """akshare拉分红，失败返回(None, 错误信息)"""
    try:
        import akshare as ak
        df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
        if df is None or df.empty:
            return None, "DataFrame为空"
        cutoff = datetime.now() - timedelta(days=365)
        total = 0.0
        found = 0
        for _, r in df.iterrows():
            date_str = str(r.get("除权除息日", "") or r.get("EX_DIVIDEND_DATE", ""))[:10]
            try:
                dd = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if dd >= cutoff:
                try:
                    val = float(r.get("每股派息", 0) or r.get("CASH_DIVIDEND", 0) or 0)
                    total += val
                    found += 1
                except (ValueError, TypeError):
                    pass
        if found > 0 and total > 0:
            return total, None
        return None, f"12个月内无分红记录(找到{found}条)"
    except Exception as e:
        return None, str(e)[:60]


def fetch_price(code):
    """push2取现价，失败回退新浪"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    for attempt in range(3):
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={"secid": secid, "fields": "f43,f57,f58"},
                headers=HEADERS, timeout=10
            )
            if attempt == 0:
                print(f"  [DEBUG] {code} push2: {r.text[:200]}")
            d = r.json()
            price = float(d.get("data", {}).get("f43", 0)) / 100
            if price > 0:
                return price
        except Exception:
            pass

    # 新浪兜底
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        m = re.search(r'="(.+?)"', r.text)
        if m:
            return float(m.group(1).split(",")[3])
    except Exception:
        pass
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
        # DPS：自动拉 + 兜底
        dps, err = fetch_dps(code)
        source = "12M实派"
        if dps is None:
            dps = v["dps"]
            source = f"兜底({err})" if err else "兜底"
        # 现价
        price = fetch_price(code)
        yld = (dps / price * 100) if price > 0 else 0
        gap = v["anchor"] - yld
        rows.append((v["name"], code, price, dps, source, yld, v["anchor"], gap))
        print(f"  {v['name']}: DPS={dps:.2f}[{source}] 价={price:.2f} 息率={yld:.2f}% 距锚{gap:+.1f}pp")

    rows.sort(key=lambda x: -x[5])

    lines = [f"## 💰 股息率周报 — {now:%Y.%m.%d}", "",
             f"> DPS：akshare 12M实派 / 兜底硬编码 ｜ {now:%m-%d %H:%M}", "",
             "| 股票 | 现价 | DPS | 来源 | 股息率 | 锚定 | 距锚定 |",
             "|------|------|-----|------|--------|------|--------|"]

    for name, code, price, dps, src, yld, anchor, gap in rows:
        ps = f"{price:.2f}" if price else "-"
        dp = f"{dps:.2f}" if dps else "-"
        ys = f"{yld:.2f}%" if yld else "-"
        gs = f"🟢 差{gap:+.1f}pp" if gap > 0 else (f"● 超额{-gap:.1f}pp" if gap < 0 else "🎯 持平")
        lines.append(f"| {name} | {ps} | {dp} | {src} | {ys} | {anchor:.1f}% | {gs} |")

    triggered = [(name, gap, yld) for name, _, _, _, _, yld, _, gap in rows if gap <= 0]
    close = [(name, gap, yld) for name, _, _, _, _, yld, _, gap in rows if gap > 0 and gap <= 0.5]

    if triggered:
        lines.append("")
        lines.append("### 🔴 已触发（股息率≥锚定）")
        for name, gap, yld in triggered:
            lines.append(f"- {name}：{yld:.2f}%（超额{-gap:.1f}pp）")
    if close:
        lines.append("")
        lines.append("### 🟡 接近触发（≤0.5pp）")
        for name, gap, yld in close:
            lines.append(f"- {name}：{yld:.2f}%，差{gap:.1f}pp")

    push(f"💰 股息率周报 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(rows)} 只")


if __name__ == "__main__":
    main()
