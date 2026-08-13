"""
估值共振 v1.0（任务⑥）
功能：买入候选的PE/PB共振判断（gap≤10% + PE≤pe_upper + PB≤pb_lower）
数据源：Tushare daily_basic（PE/PB可靠） + 东财现价
联动：共振达标 = 真买点（触发价总监控的买入候选 → 本任务确认估值）
运行：收盘后 16:00
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone
import tushare as ts

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"
BATCH_SIZE = 20
GAP_LIMIT = 10.0   # 只看 gap≤10% 的候选


def to_tscode(code):
    if code.startswith(("6", "9")):
        return code + ".SH"
    return code + ".SZ"


def to_secid(code):
    if code.startswith(("6", "9")):
        return "1." + code
    return "0." + code


def load_framework():
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}
    return data.get("trigger", {})


def fetch_prices(secids, retries=3):
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    all_diff = []
    for i in range(0, len(secids), BATCH_SIZE):
        batch = secids[i:i + BATCH_SIZE]
        ok = False
        for attempt in range(retries):
            try:
                r = requests.get(url, params={"secids": ",".join(batch), "fields": "f2,f12,f14"},
                                 headers=headers, timeout=30)
                r.raise_for_status()
                data = r.json()
                diff = data.get("data", {}).get("diff", [])
                if diff:
                    all_diff.extend(diff)
                    ok = True
                    break
            except Exception as e:
                print(f"  [东财] 第{i // BATCH_SIZE + 1}批 第{attempt+1}次失败: {e}")
            time.sleep(3)
        time.sleep(2)
    return all_diff


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        r = requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title,
            "content": content, "template": "markdown",
            "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
        print(f"  [Push] {'OK' if r.json().get('code') == 200 else r.json()}")
    except Exception as e:
        print(f"  [Push] {e}")


def latest_trade_date(pro):
    today = datetime.now(timezone.utc) + timedelta(hours=8)
    end = today.strftime("%Y%m%d")
    start = (today - timedelta(days=10)).strftime("%Y%m%d")
    try:
        df = pro.trade_cal(exchange="SSE", is_open=1, start_date=start, end_date=end)
        if df is not None and not df.empty:
            return str(df["cal_date"].max())
    except Exception as e:
        print(f"  交易日历失败: {e}")
    return end


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 估值共振 {now:%m-%d %H:%M}")

    if not TUSHARE_TOKEN:
        print("[SKIP] 未配置 TUSHARE_TOKEN")
        return

    pro = ts.pro_api(TUSHARE_TOKEN)
    trigger = load_framework()

    candidates = []
    for code, info in trigger.items():
        tp = info.get("trigger_price", 0) or 0
        if tp <= 0:
            continue
        candidates.append({
            "code": code,
            "name": info.get("name", code),
            "trigger": tp,
            "pe_upper": info.get("pe_upper", 0) or 0,
            "pb_lower": info.get("pb_lower", 0) or 0,
        })

    if not candidates:
        push(f"📊 估值共振 {now:%m-%d}", "## 估值共振\n\n无有效触发价。")
        return

    # 拉现价，筛 gap≤10% 的候选
    secids = [to_secid(c["code"]) for c in candidates]
    quotes = fetch_prices(secids)
    quote_map = {}
    for q in quotes:
        code = q.get("f12", "")
        try:
            price = float(q.get("f2", 0)) / 100
        except:
            price = 0
        if code:
            quote_map[code] = price

    near = []
    for c in candidates:
        price = quote_map.get(c["code"], 0)
        if price <= 0:
            continue
        gap = (price - c["trigger"]) / c["trigger"] * 100
        if gap <= GAP_LIMIT:
            near.append({**c, "price": price, "gap": gap})

    if not near:
        push(f"📊 估值共振 {now:%m-%d}", "## 估值共振\n\n无 gap≤10% 的候选，无需估值共振。")
        return

    # 拉 Tushare PE/PB
    trade_date = latest_trade_date(pro)
    hit = []      # 共振达标（真买点）
    near_hit = [] # 接近达标
    for c in near:
        code = c["code"]
        tscode = to_tscode(code)
        pe = pb = None
        try:
            df = pro.daily_basic(ts_code=tscode, trade_date=trade_date,
                                 fields='ts_code,pe,pb')
            if df is not None and not df.empty:
                row = df.iloc[0]
                pe = float(row.get("pe", 0) or 0) if row.get("pe") not in (None,) else None
                pb = float(row.get("pb", 0) or 0) if row.get("pb") not in (None,) else None
                try:
                    pe = float(row["pe"])
                except:
                    pe = None
                try:
                    pb = float(row["pb"])
                except:
                    pb = None
        except Exception as e:
            print(f"  {c['name']} PE/PB失败: {e}")
        time.sleep(0.3)

        c["pe"] = pe
        c["pb"] = pb

        if pe is None or pb is None:
            continue
        if pe <= c["pe_upper"] and pb <= c["pb_lower"]:
            hit.append(c)
        elif pe <= c["pe_upper"] * 1.2 and pb <= c["pb_lower"] * 1.2:
            near_hit.append(c)

    print(f"  共振达标 {len(hit)} | 接近 {len(near_hit)} | 候选 {len(near)}")

    lines = [
        f"## 📊 估值共振 {now:%m-%d %H:%M}",
        f"候选{len(near)}只 · 共振达标{len(hit)} · 接近{len(near_hit)}",
        "",
    ]

    if hit:
        lines.append("**🎯 估值共振达标（PE/PB都达标=真买点）**")
        lines.append("")
        for r in hit:
            lines.append(f"· {r['name']}({r['code']}) 现{r['price']:.2f} PE{r['pe']:.1f}(≤{r['pe_upper']}) PB{r['pb']:.2f}(≤{r['pb_lower']})")
            lines.append("")

    if near_hit:
        lines.append("**⏳ 接近共振（PE/PB接近达标）**")
        lines.append("")
        for r in near_hit:
            lines.append(f"· {r['name']}({r['code']}) 现{r['price']:.2f} PE{r['pe']:.1f}(≤{r['pe_upper']}) PB{r['pb']:.2f}(≤{r['pb_lower']})")
            lines.append("")

    lines.append("⚠️ 共振达标≠立即买：左侧分层，目标价打9折、仓位减半、观察1周。")
    lines.append("⚠️ PE/PB 来自 Tushare daily_basic（可靠），非东财脏数据。")

    push(f"📊 估值共振（达标{len(hit)}）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
