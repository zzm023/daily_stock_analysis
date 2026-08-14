"""
触发价总监控 v1.6（任务①）
功能：已触发 + 买入候选（gap≤10%） + 距触发价排行 + 建议仓位
数据源：framework_state.json（触发价/持仓） + attr_map.json（分类） + 东财实时价
联动：PE/PB共振交给「估值共振」任务（Tushare），本任务只做gap
运行：收盘后 15:45
注意：东财f2返回"分"需÷100；分批请求避免URL过长502
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"
ATTR_FILE = "attr_map.json"

GAP_CLOSE = 10.0   # 买入候选：gap ≤ 10%
RANK_TOP = 10      # 距触发价排行前 N 名
BATCH_SIZE = 20    # 每批请求的股票数

TOTAL_CAPITAL = 600000  # 总资金 60万（可改）

# 六类仓位上限
POSITION_CAP = {
    "①永续债": 0.15,   # ≤15%
    "②高息成长": 0.08,  # ≤8%
    "③周期拐点": 0.03,  # ≤3%
    "④全球寡头": 0.02,  # ≤2%
    "⑤品牌心智": 0.08,  # ≤8%
    "⑥小众冠军": 0.08,  # ≤8%
    "科技✅⚠": 0.08,    # ≤8%
}


def to_secid(code):
    if code.startswith(("6", "9")):
        return "1." + code
    return "0." + code


def load_framework():
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}, {}
    trigger = data.get("trigger", {})
    holdings = {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}
    return trigger, holdings


def load_attr_map():
    try:
        with open(ATTR_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def fetch_prices(secids, retries=3):
    """东财批量拉价，分批请求避免URL过长502"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    all_diff = []
    for i in range(0, len(secids), BATCH_SIZE):
        batch = secids[i:i + BATCH_SIZE]
        batch_no = i // BATCH_SIZE + 1
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
                print(f"  [东财] 第{batch_no}批 第{attempt+1}次失败: {e}")
            time.sleep(3)
        if not ok:
            print(f"  [东财] 第{batch_no}批 重试{retries}次仍失败")
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


def cap_line(attr, code):
    """生成建议仓位行"""
    cap = POSITION_CAP.get(attr, 0)
    if cap <= 0:
        return ""
    amt = TOTAL_CAPITAL * cap / 10000
    return f"  💰 建议仓位 {attr} ≤{cap*100:.0f}%（约{amt:.0f}万）"


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 触发价总监控 v1.6 {now:%m-%d %H:%M}")

    trigger, holdings = load_framework()
    attr_map = load_attr_map()
    hold_codes = set(holdings.keys())

    candidates = []
    for code, info in trigger.items():
        tp = info.get("trigger_price", 0) or 0
        if tp <= 0:
            continue
        candidates.append({
            "code": code,
            "name": info.get("name", code),
            "trigger": tp,
            "is_hold": code in hold_codes,
        })

    if not candidates:
        push(f"📊 触发价总监控 {now:%m-%d}", "## 触发价总监控\n\nframework_state.json 无有效触发价。")
        return

    secids = [to_secid(c["code"]) for c in candidates]
    quotes = fetch_prices(secids)
    if not quotes:
        print("[SKIP] 行情为空（所有批次均失败）")
        return

    quote_map = {}
    for q in quotes:
        code = q.get("f12", "")
        try:
            price = float(q.get("f2", 0)) / 100   # 分 → 元
        except:
            price = 0
        if code:
            quote_map[code] = price

    hit = []     # 已触发：现价 ≤ 触发价
    close = []   # 买入候选：gap ≤ 10%
    ranking = [] # 距触发价排行

    for c in candidates:
        code = c["code"]
        price = quote_map.get(code)
        if price is None or price <= 0:
            continue

        gap = (price - c["trigger"]) / c["trigger"] * 100
        row = {**c, "price": price, "gap": gap}
        ranking.append(row)

        if price <= c["trigger"]:
            hit.append(row)
        elif gap <= GAP_CLOSE:
            close.append(row)

    ranking.sort(key=lambda x: x["gap"])

    print(f"  已触发 {len(hit)} | 买入候选 {len(close)} | 拉价成功 {len(quote_map)}/{len(candidates)}")

    lines = [
        f"## 📊 触发价总监控 {now:%m-%d %H:%M}",
        f"监控{len(candidates)}只 · 触发{len(hit)} · 买入候选{len(close)}",
        "",
    ]

    if hit:
        lines.append("**🔥 已触发（现价≤触发价）**")
        lines.append("")
        for r in hit:
            tag = "｜补仓" if r["is_hold"] else "｜待买"
            lines.append(f"· {r['name']}({r['code']}) {r['price']:.2f}→{r['trigger']:.2f} 距{r['gap']:+.1f}%{tag}")
            cl = cap_line(attr_map.get(r["code"], ""), r["code"])
            if cl:
                lines.append(cl)
            lines.append("")

    if close:
        lines.append("**🎯 买入候选（距触发≤10%，估值待共振确认）**")
        lines.append("")
        for r in close:
            lines.append(f"· {r['name']}({r['code']}) {r['price']:.2f}→{r['trigger']:.2f} 距{r['gap']:+.1f}%")
            cl = cap_line(attr_map.get(r["code"], ""), r["code"])
            if cl:
                lines.append(cl)
            lines.append("")

    if ranking:
        lines.append(f"**📉 距触发价排行（前{RANK_TOP}）**")
        lines.append("")
        for i, r in enumerate(ranking[:RANK_TOP], 1):
            lines.append(f"{i}. {r['name']} {r['price']:.2f}→{r['trigger']:.2f}（{r['gap']:+.1f}%）")
            lines.append("")

    lines.append("⚠️ 买入候选仅看价格gap，PE/PB共振由「估值共振」任务确认。触发≠立即买，目标价打9折、仓位减半、观察1周。")

    push(f"📊 触发价总监控（{len(hit)}触发/{len(close)}候选）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
