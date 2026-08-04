#!/usr/bin/env python3
"""股息率周报：自动拉12个月分红DPS（akshare拉取 + 硬编码兜底）
每周一 08:00 CST
"""
import akshare as ak
import requests
import os
from datetime import datetime, timedelta

# 13只高息标的（兜底DPS，运行时优先用akshare拉真实12月分红）
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

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.eastmoney.com/"}


def fetch_latest_dps(code, fallback):
    """akshare拉近12个月每股派息；失败回退兜底"""
    try:
        df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
        if df is None or df.empty:
            return fallback, "兜底"
        cutoff = datetime.now() - timedelta(days=365)
        total = 0.0
        for _, r in df.iterrows():
            date_str = str(r.get("除权除息日", ""))[:10]
            try:
                dd = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if dd >= cutoff:
                try:
                    total += float(r.get("每股派息", 0) or 0)
                except (ValueError, TypeError):
                    pass
        if total > 0:
            return total, "12M实派"
    except Exception as e:
        print(f"  {code} DPS拉取失败: {e}")
    return fallback, "兜底"


def fetch_price(code):
    """push2取现价"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": secid, "fields": "f43"},
            headers=HEADERS, timeout=10
        )
        d = r.json()
        return float(d.get("data", {}).get("f43", 0)) / 100
    except Exception:
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
        dps, source = fetch_latest_dps(code, v["dps"])
        price = fetch_price(code)
        yld = (dps / price * 100) if price > 0 else 0
        gap = v["anchor"] - yld
        rows.append((v["name"], code, price, dps, source, yld, v["anchor"], gap))
        print(f"  {v['name']}: DPS={dps:.2f}[{source}] 价={price:.2f} 息率={yld:.2f}% 距锚{gap:+.1f}pp")

    rows.sort(key=lambda x: -x[5])  # 按股息率降序

    lines = [f"## 💰 股息率周报 — {now:%Y.%m.%d}", "",
             f"> 12个月实派DPS（akshare）｜ 兜底硬编码 ｜ {now:%m-%d %H:%M}", "",
             "| 股票 | 现价 | DPS | 来源 | 股息率 | 锚定 | 距锚定 |",
             "|------|------|-----|------|--------|------|--------|"]

    for name, code, price, dps, src, yld, anchor, gap in rows:
        ps = f"{price:.2f}" if price else "-"
        dp = f"{dps:.2f}" if dps else "-"
        ys = f"{yld:.2f}%" if yld else "-"
        gs = f"🟢 差{gap:+.1f}pp" if gap > 0 else (f"● 超额{-gap:.1f}pp" if gap < 0 else "🎯 持平")
        lines.append(f"| {name} | {ps} | {dp} | {src} | {ys} | {anchor:.1f}% | {gs} |")

    close_list = [(name, gap, yld) for name, _, _, _, _, yld, anchor, gap in rows if gap > 0 and gap <= 0.5]
    triggered = [(name, gap, yld) for name, _, _, _, _, yld, anchor, gap in rows if gap <= 0]

    if triggered:
        lines.append("")
        lines.append("### 🔴 已触发（股息率≥锚定）")
        for name, gap, yld in triggered:
            lines.append(f"- {name}：{yld:.2f}%（超额{-gap:.1f}pp）")

    if close_list:
        lines.append("")
        lines.append("### 🟡 接近触发（≤0.5pp）")
        for name, gap, yld in close_list:
            lines.append(f"- {name}：{yld:.2f}%，差{gap:.1f}pp")

    push(f"💰 股息率周报 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(rows)} 只")


if __name__ == "__main__":
    main()
