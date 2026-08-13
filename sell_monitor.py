"""
卖出决策 v1.1（任务②）
规则（左侧交易+长线持股）：
1. 翻倍止盈：盈亏≥+100% → 卖出
2. 宝信软件特殊：回本（盈亏≥+0.2%覆盖手续费税）→ 卖出
3. 基本面恶化：读earnings_events（季报追踪填充）→ 卖出警示
4. 跌破触发价 = 加仓机会（非卖出），见触发价总监控
运行：收盘后 16:30
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"

BATCH_SIZE = 20
DOUBLE_PNL = 100.0     # 翻倍止盈线（%）
RECOVER_PNL = 0.2      # 宝信软件回本线（%，覆盖手续费+税）
EXCLUDE = {"002747"}   # 埃斯顿（负成本，已了结）
BAOXIN = "600845"      # 宝信软件（框架外，回本即卖）


def to_secid(code):
    if code.startswith(("6", "9")):
        return "1." + code
    return "0." + code


def load_framework():
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}, {}, []
    trigger = data.get("trigger", {})
    holdings = {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}
    earnings = data.get("earnings_events", [])
    return trigger, holdings, earnings


def fetch_prices(secids, retries=3):
    """东财批量拉价，分批请求"""
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


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 卖出决策 {now:%m-%d %H:%M}")

    trigger, holdings, earnings = load_framework()

    # 持仓（排除埃斯顿）
    positions = []
    for code, info in holdings.items():
        if code in EXCLUDE:
            continue
        positions.append({
            "code": code,
            "name": info.get("name", code),
            "cost": info.get("cost", 0) or 0,
            "shares": info.get("shares", 0) or 0,
        })

    if not positions:
        push(f"📊 卖出决策 {now:%m-%d}", "## 卖出决策\n\n无持仓。")
        return

    secids = [to_secid(p["code"]) for p in positions]
    quotes = fetch_prices(secids)
    if not quotes:
        print("[SKIP] 行情为空（所有批次均失败）")
        return

    quote_map = {}
    for q in quotes:
        code = q.get("f12", "")
        try:
            price = float(q.get("f2", 0)) / 100
        except:
            price = 0
        if code:
            quote_map[code] = price

    # 基本面恶化清单（季报追踪任务填充 earnings_events）
    worsen_codes = set()
    for e in earnings:
        c = e.get("code", "")
        status = str(e.get("status", "")) + str(e.get("detail", ""))
        if "恶化" in status or "下滑" in status or "亏损" in status:
            worsen_codes.add(c)

    double_signals = []   # 翻倍止盈
    recover_signals = []  # 宝信回本
    worsen_signals = []   # 基本面恶化
    profit_rows = []      # 盈亏总览

    for p in positions:
        price = quote_map.get(p["code"])
        if price is None or price <= 0:
            continue

        pnl_pct = (price - p["cost"]) / p["cost"] * 100 if p["cost"] > 0 else 0
        pnl_amt = (price - p["cost"]) * p["shares"] if p["cost"] > 0 else 0
        row = {**p, "price": price, "pnl_pct": pnl_pct, "pnl_amt": pnl_amt}
        profit_rows.append(row)

        # 翻倍止盈
        if pnl_pct >= DOUBLE_PNL:
            double_signals.append(row)
        # 宝信软件：回本即卖
        elif p["code"] == BAOXIN and pnl_pct >= RECOVER_PNL:
            recover_signals.append(row)
        # 基本面恶化
        if p["code"] in worsen_codes:
            worsen_signals.append(row)

    print(f"  翻倍 {len(double_signals)} | 宝信回本 {len(recover_signals)} | 恶化 {len(worsen_signals)}")

    lines = [
        f"## 📊 卖出决策 {now:%m-%d %H:%M}",
        f"持仓{len(profit_rows)}只 · 翻倍{len(double_signals)} · 回本{len(recover_signals)} · 恶化{len(worsen_signals)}",
        "",
    ]

    if double_signals:
        lines.append("**🟢 翻倍止盈（盈亏≥100%）**")
        lines.append("")
        for r in double_signals:
            lines.append(f"· {r['name']}({r['code']}) 现{r['price']:.2f} 成本{r['cost']:.2f} 盈亏{r['pnl_pct']:+.1f}%（{r['pnl_amt']:+.0f}元）")
            lines.append("")

    if recover_signals:
        lines.append("**🟢 宝信软件回本（≥成本，含手续费税）**")
        lines.append("")
        for r in recover_signals:
            lines.append(f"· {r['name']}({r['code']}) 现{r['price']:.2f} 成本{r['cost']:.2f} 盈亏{r['pnl_pct']:+.1f}%")
            lines.append("")

    if worsen_signals:
        lines.append("**🔴 基本面恶化警示（季报追踪）**")
        lines.append("")
        for r in worsen_signals:
            lines.append(f"· {r['name']}({r['code']}) 季报恶化，审视买入逻辑")
            lines.append("")

    lines.append("**📋 持仓盈亏总览**")
    lines.append("")
    for r in profit_rows:
        mark = "🔴" if r["pnl_pct"] < 0 else "🟢"
        near_double = " ｜接近翻倍" if 80 <= r["pnl_pct"] < 100 else ""
        lines.append(f"{mark} {r['name']}({r['code']}) 现{r['price']:.2f} 成本{r['cost']:.2f} 盈亏{r['pnl_pct']:+.1f}%（{r['pnl_amt']:+.0f}元）{near_double}")
        lines.append("")

    lines.append("⚠️ 卖出三原则：翻倍→卖；基本面恶化→卖；宝信回本→卖。跌破触发价=加仓机会（左侧，非卖出）。")

    push(f"📊 卖出决策（翻倍{len(double_signals)}/回本{len(recover_signals)}/恶化{len(worsen_signals)}）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
