#!/usr/bin/env python3
"""
每周复盘 v3.5：PE / PB / 距触发价汇总
联动 framework_state.json（触发价+股票清单）+ attr_map.json（分类）
数据源：Tushare daily_basic（逐只查询）— 每周六 18:00
"""
import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
import tushare

STATE_FILE = "framework_state.json"
ATTR_FILE = "attr_map.json"
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

ATTR_ORDER = {
    "①永续债": 0, "②高息成长": 1, "③周期拐点": 2, "④全球寡头": 3,
    "⑤品牌心智": 4, "⑥小众冠军": 5, "科技✅⚠": 6,
}
ATTR_LABEL = {
    "①永续债": "🏰 ①永续债", "②高息成长": "💵 ②高息成长",
    "③周期拐点": "🔄 ③周期拐点", "④全球寡头": "🌍 ④全球寡头",
    "⑤品牌心智": "🧠 ⑤品牌心智", "⑥小众冠军": "🏆 ⑥小众冠军",
    "科技✅⚠": "⚡ 科技",
}


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] 读取 {path} 失败: {e}")
        return {}


def to_ts_code(code):
    if code.startswith("6"):
        return code + ".SH"
    elif code.startswith(("0", "3")):
        return code + ".SZ"
    elif code.startswith(("8", "4")):
        return code + ".BJ"
    return code


def get_latest_trade_date(pro, now):
    end = now.strftime("%Y%m%d")
    start = (now - timedelta(days=15)).strftime("%Y%m%d")
    try:
        df = pro.trade_cal(exchange="SSE", start_date=start, end_date=end,
                           is_open="1")
        if df is not None and not df.empty:
            days = sorted(str(d) for d in df["cal_date"].tolist())
            today = now.strftime("%Y%m%d")
            if now.hour < 17:
                days = [d for d in days if d < today]
            return days[-1] if days else None
    except Exception as e:
        print(f"  [trade_cal] {e}")
    return None


def fetch_quotes(pro, codes, latest_td):
    lookup = {}
    start = (datetime.strptime(latest_td, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d")
    for code in codes:
        tsc = to_ts_code(code)
        try:
            df = pro.daily_basic(ts_code=tsc, start_date=start, end_date=latest_td,
                                 fields="ts_code,trade_date,close,pe,pb")
            if df is not None and not df.empty:
                df = df.sort_values("trade_date")
                row = df.iloc[-1]
                try:
                    price = float(row["close"]) if row["close"] else 0
                except:
                    price = 0
                try:
                    pe = float(row["pe"]) if row["pe"] else 0
                except:
                    pe = 0
                try:
                    pb = float(row["pb"]) if row["pb"] else 0
                except:
                    pb = 0
                lookup[code] = {"price": price, "pe": pe, "pb": pb}
        except Exception as e:
            print(f"  [{code}] {e}")
        time.sleep(0.15)
    return lookup


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("[WARN] 无TOKEN")
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title,
                   "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
        print(f"[{'OK' if r.json().get('code') == 200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 每周复盘 v3.5 {now:%Y-%m-%d %H:%M}")

    if not TUSHARE_TOKEN:
        print("[SKIP] 未配置 TUSHARE_TOKEN")
        return

    pro = tushare.pro_api(TUSHARE_TOKEN)
    state = load_json(STATE_FILE)
    attr_map = load_json(ATTR_FILE)
    trigger = state.get("trigger", {})

    stocks = []
    for code, info in trigger.items():
        stocks.append({
            "code": code,
            "name": info.get("name", code),
            "attr": attr_map.get(code, "其他"),
        })

    latest_td = get_latest_trade_date(pro, now)
    print(f"  最近交易日: {latest_td}")
    if not latest_td:
        push(f"📊 每周复盘 {now:%Y.%m.%d}", "## 📊 每周复盘\n\n无法获取交易日。")
        return

    data = fetch_quotes(pro, [s["code"] for s in stocks], latest_td)
    print(f"  行情覆盖: {len(data)}/{len(stocks)}")

    lines = [f"## 📊 每周复盘 — {now:%Y.%m.%d}", "",
             f"> PE / PB / 距触发价 ｜ 数据日 {latest_td}", ""]

    stocks_sorted = sorted(stocks, key=lambda s: (ATTR_ORDER.get(s["attr"], 99), s["code"]))
    cur, total, hit, close_10 = None, 0, 0, 0

    for s in stocks_sorted:
        g = ATTR_LABEL.get(s["attr"], s["attr"])
        if g != cur:
            cur = g
            lines.append(f"### {g}")
            lines.append("")

        code = s["code"]
        row = data.get(code, {})
        price = row.get("price", 0)
        pe = row.get("pe", 0)
        pb = row.get("pb", 0)

        tp = trigger.get(code, {}).get("trigger_price", 0)

        ps = f"{price:.2f}" if price else "-"
        pes = f"{pe:.1f}" if pe else "-"
        pbs = f"{pb:.2f}" if pb else "-"

        if tp and price:
            gap = (price - tp) / tp * 100
            if gap <= 0:
                gs = f"🔴 {gap:+.1f}%"; hit += 1
            elif gap < 10:
                gs = f"🟡 {gap:+.1f}%"; close_10 += 1
            else:
                gs = f"⚪ {gap:+.1f}%"
            ts = f"{tp:.2f}"
        else:
            gs = "-"
            ts = "-"

        lines.append(f"**{s['name']}** {ps} PE{pes} PB{pbs}")
        lines.append(f"> 触发价 {ts} 差距 {gs}")
        lines.append("")
        total += 1

    lines.insert(4, f"> 🔴已触发:{hit} | 🟡近触发(10%):{close_10} | ⚪安全区:{total-hit-close_10}")
    lines.insert(5, "")

    push(f"📊 每周复盘 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {total} 只")


if __name__ == "__main__":
    main()
