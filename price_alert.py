"""
价格异动监控（盘中实时）v5
① 触价即报：现价 ≤ 触发价（framework_state.json trigger_price，每日每只一次）
② 涨跌幅异动：持仓(±3%) + 所有设触发价的观察股(±5%)
   v5变更：取消观察股 10% gap 过滤——触发价下调后个股会跌出监控圈导致漏报，
   现改为框架内所有 trigger_price>0 的股票都监控。
数据源：framework_state.json（触发价+持仓） + 东财实时价
"""

import os, json, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

FRAMEWORK_FILE = "framework_state.json"
STATE_FILE = "price_alert_state.json"

HOLD_THRESHOLD = 3.0    # 持仓 ±3%
WATCH_THRESHOLD = 5.0   # 观察 ±5%
LEVELS = [3.0, 5.0, 7.0, 9.0]

EXCLUDE = {"002747"}    # 埃斯顿（负成本，不监控）


def to_secid(code):
    """6位代码 → 东财secid"""
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


def fetch_quotes(secids):
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"secids": ",".join(secids), "fields": "f2,f3,f12,f14"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    r = None
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("data", {}).get("diff", [])
    except Exception as e:
        snippet = repr(r.text[:200]) if r is not None else ""
        print(f"  [东财] {e} | 响应: {snippet}")
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
    """读 framework_state.json → (trigger价dict, 持仓dict)"""
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

    # 候选：持仓(除EXCLUDE) + trigger_price>0 的观察股
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
        state0 = load_state()
        key = f"err_{now.strftime('%Y%m%d')}_nocand"
        if not state0.get(key):
            push("⚠️ 盘中监控无候选",
                 "## ⚠️ 盘中异动\n\nframework_state.json 无有效候选（触发价/持仓为空）。请检查仓库数据文件。")
            state0[key] = 1
            save_state(state0)
        else:
            print("[SKIP] 无候选（今日已告警一次）")
        return

    # 拉实时价
    secids = [to_secid(c) for c in candidates.keys()]
    quotes = fetch_quotes(secids)
    if not quotes:
        state0 = load_state()
        key = f"err_{now.strftime('%Y%m%d')}_quotes"
        if not state0.get(key):
            push("⚠️ 盘中行情拉取失败",
                 "## ⚠️ 盘中异动\n\n东财行情接口无数据。可能是接口临时故障，10分钟后自动重试。")
            state0[key] = 1
            save_state(state0)
        else:
            print("[SKIP] 行情为空（今日已告警一次）")
        return

    price_map = {}
    for q in quotes:
        code = q.get("f12", "")
        try:
            price = float(q.get("f2", 0))
        except:
            price = 0
        if code in candidates:
            price_map[code] = {
                "price": price,
                "change": float(str(q.get("f3", "0")).replace("%", "")),
            }

    state = load_state()
    today = now.strftime("%Y%m%d")
    move_alerts = []
    cross_alerts = []
    watch_count = 0

    for code, meta in candidates.items():
        if code not in price_map:
            continue
        price = price_map[code]["price"]
        change = price_map[code]["change"]
        tp = meta["trigger"]

        # ① 触价即报：现价 ≤ 触发价（不受 gap 过滤限制，每日每只一次）
        if tp > 0 and price > 0 and price <= tp:
            key = f"hit_{today}_{code}"
            if not state.get(key):
                cross_alerts.append((meta["name"], code, price, tp, meta["is_hold"]))
                state[key] = 1

        # ② 涨跌幅异动（原逻辑）
        if meta["is_hold"]:
            threshold = HOLD_THRESHOLD
            watch_count += 1
        else:
            if price <= 0:
                continue
            # v5：所有设触发价的观察股都监控涨跌幅，不再用 gap 过滤
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

        move_alerts.append((meta["name"], code, change, cur_level, meta["is_hold"], price, meta["trigger"]))
        state[key] = cur_level

    if not cross_alerts and not move_alerts:
        save_state(state)
        print(f"[DONE] 无新异动，监控{watch_count}只 {now:%m-%d %H:%M}")
        return

    lines = [f"## ⚡ 价格异动 {now:%m-%d %H:%M}", ""]

    if cross_alerts:
        lines.append("### 🎯 触达触发价（现价 ≤ 触发价）")
        for name, code, price, tp, is_hold in cross_alerts:
            tag = "持仓·补仓" if is_hold else "待买"
            lines.append(f"**{name}**({code}) [{tag}] 现价 {price:.2f} ≤ 触发价 {tp:.2f}")
        lines.append("")
        lines.append("> ⚠️ 触发 ≠ 立即买。左侧分层：目标价打9折、仓位减半、观察1周。")
        lines.append("")

    if move_alerts:
        lines.append("### 📈 涨跌幅异动")
        for name, code, change, lv, is_hold, price, tp in move_alerts:
            tag = "持仓" if is_hold else "观察"
            arrow = "🔴" if change < 0 else "🟢"
            gap_str = ""
            if not is_hold and tp > 0:
                gap_str = f"（距触发价{(price - tp) / tp * 100:.1f}%）"
            lines.append(f"{arrow} **{name}**({code}) [{tag}] 涨跌 **{change:+.2f}%**（≥{lv:.0f}%档）{gap_str}")
        lines.append("")

    lines.append(f"---\n盘中监控 {watch_count}只 · {now:%m-%d %H:%M}")

    title = f"🎯 触达触发价（{len(cross_alerts)}只）" if cross_alerts else f"⚡ 异动 {now:%m-%d %H:%M}（{len(move_alerts)}只）"
    push(title, "\n".join(lines))
    save_state(state)
    print(f"[DONE] 触价{len(cross_alerts)}条 / 异动{len(move_alerts)}条")


if __name__ == "__main__":
    main()
