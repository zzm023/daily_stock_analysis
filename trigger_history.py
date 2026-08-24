#!/usr/bin/env python3
"""
触发价历史追溯 + 校准提醒 v12
1. 股息率锚校准（保留）：dps/锚定股息率 对应价 vs 触发价，偏离±15%提醒
2. 近期波动验证（升级）：多窗口低点 60/90/180/250自然日 + 低点日期
   - 主窗口按属性分层：①永续债/③周期→250 ②高息→180 ④⑤⑥/科技→90
   - 穿透深度分档：≤5%观察 | 5~15%下修审查 | >15%基本面复查
   - 多窗口共振（≥2档穿透）单独提示
铁律：只提醒，不自动改触发价。价格新低≠下修理由，仅基本面锚(dps/EPS/扣非)变化才下修。
数据源：framework_state.json + Tushare daily
运行：周一 08:00
"""
import os
import json
import requests
from datetime import datetime, timedelta, timezone
import tushare

STATE_FILE = "framework_state.json"
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

THRESHOLD = 15.0            # 股息率锚偏离阈值 ±15%
MAX_LOOKBACK = 250          # 拉数上限（自然日）。③周期股理想500，受上限约束主窗口取250
WINDOWS = [60, 90, 180, 250]  # 多窗口低点
BATCH = 20                  # tushare daily 单次行数限制，分片拉取

# 主窗口分层（自然日），与 earnings_monitor.py 的 ALL_STOCKS 属性表一致：
# ①永续债/③周期→250（周期理想500，受数据上限约束） ②高息→180 其余→90
MAIN_WINDOW = {
    # ①永续债
    "600036": 250, "601601": 250, "600018": 250, "601816": 250,
    "600900": 250, "600941": 250, "600406": 250, "600598": 250,
    "603568": 250, "600007": 250, "000429": 250,
    # ②高息成长
    "000895": 180, "000848": 180,
    # ③周期拐点
    "000157": 250, "600585": 250, "000792": 250, "600188": 250,
    "002601": 250, "600299": 250, "300498": 250,
}


def main_window(code, t):
    """主窗口：映射表优先 → 有股息锚兜底180 → 默认90"""
    if code in MAIN_WINDOW:
        return MAIN_WINDOW[code]
    if t.get("dps") and t.get("anchor_pct"):
        return 180
    return 90


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


def fetch_lows(pro, codes, latest_td):
    """分片拉近250自然日 daily，返回 {code: {win: {"date":..,"low":..}}}"""
    ts_codes = [to_ts_code(c) for c in codes]
    start = (datetime.strptime(latest_td, "%Y%m%d") - timedelta(days=MAX_LOOKBACK)).strftime("%Y%m%d")
    raw = {}
    for i in range(0, len(ts_codes), BATCH):
        batch = ts_codes[i:i + BATCH]
        try:
            df = pro.daily(ts_code=",".join(batch), start_date=start, end_date=latest_td,
                           fields="ts_code,trade_date,low")
        except Exception as e:
            print(f"  [daily] {e}")
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            try:
                d = str(row["trade_date"])
                l = float(row["low"])
                raw.setdefault(str(row["ts_code"]), []).append((d, l))
            except Exception:
                continue

    latest_dt = datetime.strptime(latest_td, "%Y%m%d")
    result = {}
    for code in codes:
        rows = raw.get(to_ts_code(code), [])
        if not rows:
            continue
        entry = {}
        for n in WINDOWS:
            cutoff = (latest_dt - timedelta(days=n)).strftime("%Y%m%d")
            sub = [(d, l) for d, l in rows if d >= cutoff]
            if sub:
                d, l = min(sub, key=lambda r: r[1])
                entry[n] = {"date": d, "low": l}
        if entry:
            result[code] = entry
    return result


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


def fmt_date(d):
    """'YYYYMMDD' → 'YY-MM-DD'"""
    return f"{d[2:4]}-{d[4:6]}-{d[6:]}" if len(d) >= 8 else d


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 触发价追溯+校准 v12 {now:%Y-%m-%d}")

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
    lows = fetch_lows(pro, codes, latest_td)
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

    # ── 2. 近期波动验证（主窗口分层 + 多窗口低点） ──
    pierced, close, far = [], [], []
    for code in codes:
        t = trigger[code]
        tp = t.get("trigger_price", 0)
        name = t.get("name", code)
        entry = lows.get(code)
        if not tp or not entry:
            continue
        win = main_window(code, t)
        w = entry.get(win)
        if not w:
            continue
        low, low_date = w["low"], w["date"]
        if low <= tp:
            depth = round((tp - low) / low * 100, 1)
            pierced.append((name, code, tp, low, low_date, win, depth))
        else:
            gap = round((low - tp) / tp * 100, 1)
            if gap <= 5:
                close.append((name, code, tp, low, low_date, win, gap))
            else:
                far.append((name, code, tp, low, low_date, win, gap))

    watch = [p for p in pierced if p[6] <= 5]      # 穿透≤5% 观察
    review = [p for p in pierced if 5 < p[6] <= 15]  # 穿透5~15% 下修审查
    alarm = [p for p in pierced if p[6] > 15]      # 穿透>15% 基本面复查

    # 多窗口共振：≥2档窗口低点均≤触发价
    resonance = []
    for code in codes:
        t = trigger[code]
        tp = t.get("trigger_price", 0)
        entry = lows.get(code)
        if not tp or not entry:
            continue
        hits = {n: entry[n] for n in WINDOWS if n in entry and entry[n]["low"] <= tp}
        if len(hits) >= 2:
            resonance.append((t.get("name", code), code, tp, hits))

    # ── 3. 推送 ──
    lines = [f"## 🎯 触发价追溯+校准 {now:%m.%d}", "",
             f"> 数据日 {latest_td} | 低点覆盖 {len(lows)}/{len(codes)}", ""]

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
    lines.append("### 近期波动验证（主窗口：①③=250 ②=180 其余=90 自然日）")
    lines.append("")
    lines.append(f"> 已击球区 {len(pierced)} | 距触发≤5% {len(close)} | 偏严 {len(far)}")
    lines.append("")

    if pierced:
        if watch:
            lines.append("**🟡 穿透≤5% · 观察（核对分层买入执行）**")
            for name, code, tp, low, d, win, depth in sorted(watch, key=lambda x: -x[6])[:8]:
                lines.append(f"- {name} 触发{tp:.2f} {win}日低{low:.2f}({fmt_date(d)}) 穿透{depth}%")
            lines.append("")
        if review:
            lines.append("**🔶 穿透5~15% · 下修审查（核 dps/EPS/扣非；无恶化→维持，折扣扩大=机会）**")
            for name, code, tp, low, d, win, depth in sorted(review, key=lambda x: -x[6])[:8]:
                lines.append(f"- {name} 触发{tp:.2f} {win}日低{low:.2f}({fmt_date(d)}) 穿透{depth}%")
            lines.append("")
        if alarm:
            lines.append("**🔴 穿透>15% · 基本面复查（锚可能失效，重新深度分析）**")
            for name, code, tp, low, d, win, depth in sorted(alarm, key=lambda x: -x[6])[:8]:
                lines.append(f"- {name} 触发{tp:.2f} {win}日低{low:.2f}({fmt_date(d)}) 穿透{depth}%")
            lines.append("")
    else:
        lines.append("**✅ 无穿透**")
        lines.append("")

    if close:
        lines.append("**距触发≤5%（接近）**")
        for name, code, tp, low, d, win, gap in sorted(close, key=lambda x: x[6])[:10]:
            lines.append(f"- {name} 触发{tp:.2f} {win}日低{low:.2f}({fmt_date(d)}) 距{gap}%")
        lines.append("")
    if far:
        lines.append(f"**距触发>5%（偏严，{len(far)}只）**")
        for name, code, tp, low, d, win, gap in sorted(far, key=lambda x: x[6])[:8]:
            lines.append(f"- {name} 触发{tp:.2f} {win}日低{low:.2f}({fmt_date(d)}) 距{gap}%")
        lines.append("")

    if resonance:
        lines.append("**⚠️ 多窗口共振（≥2档穿透，真信号）**")
        for name, code, tp, hits in resonance[:10]:
            parts = []
            for n in sorted(hits):
                parts.append(f"{n}日低{hits[n]['low']:.2f}({fmt_date(hits[n]['date'])})")
            lines.append(f"- {name} 触发{tp:.2f} | " + " | ".join(parts))
        lines.append("")

    lines.append("---")
    lines.append("只提醒不自动改触发价 | 下修决策树：价格新低≠下修，仅dps/EPS/扣非锚变化才下修 | "
                 + f"{now:%m-%d %H:%M}")

    push(f"🎯 触发价追溯+校准 {now:%m.%d}", "\n".join(lines))
    print(f"[DONE] 股息锚偏离{len(anchor_alerts)} 击球{len(pierced)}"
          f"(观察{len(watch)}/审查{len(review)}/复查{len(alarm)}) "
          f"接近{len(close)} 偏严{len(far)} 共振{len(resonance)}")


if __name__ == "__main__":
    main()
