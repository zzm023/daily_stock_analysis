"""
价格异动监控（盘中实时）v3.3
和触发价联动：持仓(±3%) + gap≤10%观察股(±5%)
数据源：framework_state.json（触发价+持仓） + 东财实时价
涨跌幅 = (最新价f2 - 昨收f18) / 昨收f18，自算
注意：东财f2/f18返回"分"，需÷100转元
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

FRAMEWORK_FILE = "framework_state.json"
STATE_FILE = "price_alert_state.json"

HOLD_THRESHOLD = 3.0    # 持仓 ±3%
WATCH_THRESHOLD = 5.0   # 观察 ±5%
GAP_LIMIT = 10.0        # 观察股 gap≤10% 才监控（%）
LEVELS = [3.0, 5.0, 7.0, 9.0]

EXCLUDE = {"002747"}    # 埃斯顿（负成本，不监控）


def to_secid(code):
    if code.startswith(("6", "9")):
        return "1." + code
    return "0." + code


def is_trading_time(now):
    hm = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= hm <= 11 * 60 + 30) or (13 * 60 <= hm <= 15 * 60)


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


def fetch_quotes(secids, retries=3):
    """东财批量：f2现价 f12代码 f14名称 f18昨收，带重试"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"secids": ",".join(secids), "fields": "f2,f12,f14,f18"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            diff = data.get("data", {}).get("diff", [])
            if diff:
                return diff
        except Exception as e:
            print(f"  [东财] 第{attempt+1}次失败: {e}")
        time.sleep(3)
    return []


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def load_framework():
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}, {}
    trigger = data.get("trigger", {})
    holdings = {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}
    return trigger, holdings


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)

    if now.weekday() >= 5 or not is_trading_time(now):
        print(f"[SKIP] 非交易时段 {now:%m-%d %H:%M}")
        return

    trigger, holdings = load_framework()

    candidates = {}
    for code, info in holdings.items():
        if code in EXCLUDE:
            continue
        candidates[code] = {"name": info.get("name", code), "is_hold": True, "trigger": 0}

    for code, info in trigger.items():
        tp = info.get("trigger_price", 0) or 0
        if tp <= 0:
            continue
        if code in candidates:
            candidates[code]["trigger"] = tp
        else:
            candidates[code] = {"name": info.get("name", code), "is_hold": False, "trigger": tp}

    if not candidates:
        print("[SKIP] 无候选")
        return

    secids = [to_secid(c) for c in candidates.keys()]
    quotes = fetch_quotes(secids)
    if not quotes:
        print("[SKIP] 行情为空（重试3次仍失败）")
        return

    price_map = {}
    for q in quotes:
        code = q.get("f12", "")
        try:
            price = float(q.get("f2", 0)) / 100        # 分 → 元
            prev_close = float(q.get("f18", 0)) / 100  # 分 → 元
        except:
            price = 0
            prev_close = 0
        if code not in candidates:
            continue
        change = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0
        price_map[code] = {"price": price, "change": change}

    state = load_state()
    today = now.strftime("%Y%m%d")
    alerts = []
    watch_count = 0

    for code, meta in candidates.items():
        if code not in price_map:
            continue
        price = price_map[code]["price"]
        change = price_map[code]["change"]

        if meta["is_hold"]:
            threshold = HOLD_THRESHOLD
            watch_count += 1
        else:
            tp = meta["trigger"]
            if price <= 0:
                continue
            gap = (price - tp) / tp * 100
            if gap > GAP_LIMIT:
                continue
            threshold = WATCH_THRESHOLD
            watch_count += 1

        abs_chg = abs(change)
        if abs_chg < threshold:
            continue

        cur_level = 0.0
        for lv in LEVELS:
            if abs_chg >= lv:
                cur_level = lv

        key = f"{today}_{code}"
        if cur_level <= state.get(key, 0):
            continue

        alerts.append((meta["name"], code, change, cur_level, meta["is_hold"], price, meta["trigger"]))
        state[key] = cur_level

    if not alerts:
        save_state(state)
        print(f"[DONE] 无新异动，监控{watch_count}只 {now:%m-%d %H:%M}")
        return

    lines = [f"## ⚡ 价格异动 {now:%m-%d %H:%M}", ""]
    for name, code, change, lv, is_hold, price, tp in alerts:
        tag = "持仓" if is_hold else "观察"
        arrow = "🔴" if change < 0 else "🟢"
        gap_str = ""
        if not is_hold and tp > 0:
            gap_str = f"（距触发价{(price - tp) / tp * 100:.1f}%）"
        lines.append(f"{arrow} **{name}**({code}) [{tag}] 涨跌 **{change:+.2f}%**（≥{lv:.0f}%档）{gap_str}")
    lines.append("")
    lines.append(f"---\n盘中监控 {watch_count}只 · {now:%m-%d %H:%M}")

    push(f"⚡ 异动 {now:%m-%d %H:%M}（{len(alerts)}只）", "\n".join(lines))
    save_state(state)
    print(f"[DONE] 推送 {len(alerts)} 条")


if __name__ == "__main__":
    main()
