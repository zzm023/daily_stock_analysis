"""
股息率周报 v3 — Tushare版
数据源：Tushare分红 + 新浪现价
"""
import requests, re, os, json, time
from datetime import datetime, timedelta
from pathlib import Path

TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

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

CUTOFF = (datetime.now() - timedelta(days=540)).date()


def _to_ts_code(code):
    if "." in code: return code
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def fetch_dps_tushare(code):
    """Tushare: 取最近12个月分红合计"""
    try:
        ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
        requests.post("https://api.tushare.pro", json={
            "api_name": "ip_whitelist", "token": TOKEN, "params": {"ip": ip}}, timeout=10)

        ts = _to_ts_code(code)
        r = requests.post("https://api.tushare.pro", json={
            "api_name": "dividend",
            "token": TOKEN,
            "params": {"ts_code": ts},
            "fields": "ts_code,cash_div,end_date",
        }, timeout=30)
        d = r.json()
        if d.get("code") != 0:
            return None, "Tushare失败"
        rows = d["data"]["items"]
        total, found = 0.0, 0
        for row in rows:
            cash_div = row[1]
            ed = str(int(row[2]))
            if not cash_div:
                continue
            try:
                div_date = datetime.strptime(ed[:8], "%Y%m%d").date()
            except:
                continue
            if div_date >= CUTOFF:
                total += float(cash_div)
                found += 1

        if found > 0 and total > 0:
            return round(total, 3), f"12M({found}条)"
        return None, f"12M无(共{len(rows)}条)"
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
        except: pass
    return 0


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC: payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    except: pass


def main():
    now = datetime.now()
    print(f"[START] 股息率周报 v3 {now:%Y-%m-%d}")

    rows = []
    for code, v in DIV.items():
        dps, src = fetch_dps_tushare(code)
        if dps is None:
            dps = v["dps"]
            src = "兜底"

        price = fetch_price(code)
        yld = (dps / price * 100) if price > 0 else 0
        gap = v["anchor"] - yld
        rows.append((v["name"], code, price, dps, src, yld, v["anchor"], gap))
        print(f"  {v['name']}: DPS={dps:.3f}[{src}] 价={price:.2f} 息率={yld:.2f}%")
        time.sleep(0.2)

    # ── 推送 ──
    rows.sort(key=lambda x: -x[5])
    lines = [f"## 💰 股息率周报 — {now:%Y.%m.%d}", "",
             f"> DPS：Tushare 12M ｜ 现价：新浪 ｜ {now:%m-%d %H:%M}", ""]

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
