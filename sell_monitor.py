"""
卖出决策 v1.0（任务②）
功能：持仓盈亏总览 + 跌破触发价卖出信号
数据源：framework_state.json（持仓/触发价） + 东财实时价（分批拉取）
运行：收盘后 16:30
注意：东财f2返回"分"需÷100；跌破触发价=卖出警示（非自动卖出）
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"

BATCH_SIZE = 20
EXCLUDE = {"002747"}   # 埃斯顿（负成本，已了结，不监控）


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

    trigger, holdings = load_framework()

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
            "trigger": trigger.get(code, {}).get("trigger_price", 0) or 0,
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
            price = float(q.get("f2", 0)) / 100   # 分 → 元
        except:
            price = 0
        if code:
            quote_map[code] = price

    sell_signals = []  # 跌破触发价
    profit_rows = []   # 盈亏总览

    for p in positions:
        price = quote_map.get(p["code"])
        if price is None or price <= 0:
            continue

        pnl_pct = (price - p["cost"]) / p["cost"] * 100 if p["cost"] > 0 else 0
        pnl_amt = (price - p["cost"]) * p["shares"] if p["cost"] > 0 else 0
        row = {**p, "price": price, "pnl_pct": pnl_pct, "pnl_amt": pnl_amt}
        profit_rows.append(row)

        # 跌破触发价 = 卖出警示
        if p["trigger"] > 0 and price < p["trigger"]:
            row["gap"] = (price - p["trigger"]) / p["trigger"] * 100
            sell_signals.append(row)

    print(f"  卖出信号 {len(sell_signals)} | 持仓 {len(profit_rows)}")

    lines = [
        f"## 📊 卖出决策 {now:%m-%d %H:%M}",
        f"持仓{len(profit_rows)}只 · 跌破触发价{len(sell_signals)}只",
        "",
    ]

    if sell_signals:
        lines.append("**🔴 卖出警示（现价跌破触发价）**")
        lines.append("")
        for r in sell_signals:
            lines.append(f"· {r['name']}({r['code']}) 现{r['price']:.2f} 触发{r['trigger']:.2f} 距{r['gap']:+.1f}% 成本{r['cost']:.2f}")
            lines.append("")
        lines.append("> 跌破触发价≠立即卖，需结合季报恶化、逻辑破坏综合判断。")
        lines.append("")

    lines.append("**📋 持仓盈亏总览**")
    lines.append("")
    for r in profit_rows:
        pnl_mark = "🔴" if r["pnl_pct"] < 0 else "🟢"
        trig_str = f" 触发{r['trigger']:.2f}" if r["trigger"] > 0 else ""
        lines.append(f"{pnl_mark} {r['name']}({r['code']}) 现{r['price']:.2f} 成本{r['cost']:.2f} 盈亏{r['pnl_pct']:+.1f}%（{r['pnl_amt']:+.0f}元）{trig_str}")
        lines.append("")

    lines.append("⚠️ 卖出纪律：逻辑破坏→卖；季报恶化→卖；跌破触发价→审视是否补错仓。其余持有收租。")

    push(f"📊 卖出决策（{len(sell_signals)}警示）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
