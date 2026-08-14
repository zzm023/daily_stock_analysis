#!/usr/bin/env python3
"""
触发价历史追溯 + 校准提醒 v11
1. 股息率锚校准（新增）：dps/锚定股息率 对应价 vs 触发价，偏离±15%提醒
2. 近期波动验证（保留）：触发价 vs 近60日低点（Tushare daily）
铁律：只提醒，不自动改触发价
数据源：framework_state.json + Tushare daily
运行：周一 08:00
"""
import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
import tushare

STATE_FILE = "framework_state.json"
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

THRESHOLD = 15.0  # 股息率锚偏离阈值 ±15%


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] 读取 {STATE_FILE} 失败: {e}")
        return {"trigger": {}}


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


def fetch_recent_lows(pro, codes, latest_td):
    """Tushare daily 批量拿近90日最低价"""
    lows = {}
    ts_codes = ",".join(to_ts_code(c) for c in codes)
    start = (datetime.strptime(latest_td, "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
    try:
        df = pro.daily(ts_code=ts_codes, start_date=start, end_date=latest_td,
                       fields="ts_code,low")
        if df is not None and not df.empty:
            for code in codes:
                tsc = to_ts_code(code)
                sub = df[df["ts_code"] == tsc]
                if not sub.empty:
                    try:
                        lows[code] = float(sub["low"].min())
                    except:
                        pass
    except Exception as e:
        print(f"  [daily] {e}")
    return lows


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
    print(f"[START] 触发价追溯+校准 v11 {now:%Y-%m-%d}")

    if not TUSHARE_TOKEN:
        print("[SKIP] 未配置 TUSHARE_TOKEN")
        return

    pro = tushare.pro_api(TUSHARE_TOKEN)
    state = load_state()
    trigger = state.get("trigger", {})

    latest_td = get_latest_trade_date(pro, now)
    print(f"  最近交易日: {latest_td}")
    if not latest_td:
        return

    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    lows = fetch_recent_lows(pro, codes, latest_td)
    print(f"  近期低点覆盖: {len(lows)}/{len(codes)}")

    # ── 1. 股息率锚校准 ──
    anchor_alerts = []
    for code in codes:
        t = trigger[code]
        dps = t.get("dps", 0)
        anchor = t.get("anchor_pct", 0)
        tp = t.get("trigger_price", 0)
        name = t.get("name", code)
        if not (dps and anchor and tp):
            continue
        target = dps / (anchor / 100.0)
        dev = (target - tp) / tp * 100
        if abs(dev) >= THRESHOLD:
            anchor_alerts.append((name, code, tp, target, dev, dps, anchor))

    # ── 2. 近期波动验证 ──
    hit, close, far = [], [], []
    for code in codes:
        t = trigger[code]
        tp = t.get("trigger_price", 0)
        name = t.get("name", code)
        low = lows.get(code)
        if not tp or low is None:
            continue
        if low <= tp:
            gap = round((tp - low) / low * 100, 1)
            hit.append((name, tp, low, gap))
        else:
            gap = round((low - tp) / tp * 100, 1)
            if gap <= 5:
                close.append((name, tp, low, gap))
            else:
                far.append((name, tp, low, gap))

    # ── 3. 推送 ──
    lines = [f"## 🎯 触发价追溯+校准 {now:%m.%d}", "",
             f"> 数据日 {latest_td} | 近期低点覆盖 {len(lows)}/{len(codes)}", ""]

    # 股息率锚校准部分
    if anchor_alerts:
        lines.append(f"### ⚠️ 股息率锚偏离（需重估，±{THRESHOLD:.0f}%）")
        lines.append("")
        for name, code, tp, target, dev, dps, anchor in anchor_alerts:
            direction = "↑ 该上调" if dev > 0 else "↓ 该下调"
            lines.append(f"- **{name}**({code}) {direction}")
            lines.append(f"  触发价 {tp:.2f} → 股息率对应价 {target:.2f}（偏离 {dev:+.1f}%）")
            lines.append(f"  依据 DPS {dps:.3f} ÷ {anchor:.1f}%")
        lines.append("")
    else:
        lines.append("### ✅ 股息率锚：无偏离超阈值")
        lines.append("")

    # 近期波动验证部分
    lines.append(f"### 近期波动验证（近90日低点 vs 触发价）")
    lines.append("")
    lines.append(f"> 触发过 {len(hit)} | 距触发≤5% {len(close)} | 偏严 {len(far)}")
    lines.append("")

    if hit:
        lines.append(f"**触发过（价合理）**")
        for name, tp, low, gap in sorted(hit, key=lambda x: -x[3])[:8]:
            lines.append(f"- {name} 触发{tp:.2f} 近期低{low:.2f} 穿透{gap}%")
        lines.append("")
    if close:
        lines.append(f"**距触发≤5%（接近）**")
        for name, tp, low, gap in sorted(close, key=lambda x: x[3])[:10]:
            lines.append(f"- {name} 触发{tp:.2f} 近期低{low:.2f} 距{gap}%")
        lines.append("")
    if far:
        lines.append(f"**距触发>5%（偏严，{len(far)}只）**")
        for name, tp, low, gap in sorted(far, key=lambda x: x[3])[:8]:
            lines.append(f"- {name} 触发{tp:.2f} 近期低{low:.2f} 距{gap}%")
        lines.append("")

    lines.append("---")
    lines.append(f"只提醒不自动改触发价 | {now:%m-%d %H:%M}")

    push(f"🎯 触发价追溯+校准 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] 股息锚偏离{len(anchor_alerts)} 触发过{len(hit)} 接近{len(close)} 偏严{len(far)}")


if __name__ == "__main__":
    main()
