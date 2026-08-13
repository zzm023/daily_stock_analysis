"""
持仓体检 v1.0（任务③）
功能：仓位风控（单只vs预算 + 属性类别vs六类七层上限）
数据源：framework_state.json（持仓/现金） + 东财现价 + 属性预算映射
运行：收盘后 16:30（每日）
注意：东财f2返回"分"需÷100；属性/预算严格取framework_stocks.md
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"
BATCH_SIZE = 20

# 持仓股属性 + 买入预算（来源 framework_stocks.md，勿随意改）
HOLDINGS_META = {
    "600845": {"attr": "框架外", "budget": 0},
    "600161": {"attr": "⑥小众冠军", "budget": 18000},
    "300498": {"attr": "③周期拐点", "budget": 12000},
    "002601": {"attr": "③周期拐点", "budget": 24000},
    "002027": {"attr": "⑤品牌心智", "budget": 36000},
    "000708": {"attr": "④全球寡头", "budget": 30000},
    "600690": {"attr": "④全球寡头", "budget": 36000},
    "000157": {"attr": "③周期拐点", "budget": 36000},
}

# 六类七层仓位上限（占总资产%）
ATTR_CAP = {
    "①永续债": 15,
    "②高息成长": 8,
    "③周期拐点": 3,
    "④全球寡头": 2,
    "⑤品牌心智": 8,
    "⑥小众冠军": 8,
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
        return {}, 0
    holdings = {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}
    cash = data.get("holdings", {}).get("cash", 0)
    return holdings, cash


def fetch_prices(secids, retries=3):
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
    print(f"[START] 持仓体检 {now:%m-%d %H:%M}")

    holdings, cash = load_framework()

    # 持仓（仅框架内 + 框架外宝信）
    positions = []
    for code, info in holdings.items():
        if code not in HOLDINGS_META:
            continue
        positions.append({
            "code": code,
            "name": info.get("name", code),
            "cost": info.get("cost", 0) or 0,
            "shares": info.get("shares", 0) or 0,
            "attr": HOLDINGS_META[code]["attr"],
            "budget": HOLDINGS_META[code]["budget"],
        })

    if not positions:
        push(f"📊 持仓体检 {now:%m-%d}", "## 持仓体检\n\n无持仓。")
        return

    secids = [to_secid(p["code"]) for p in positions]
    quotes = fetch_prices(secids)
    if not quotes:
        print("[SKIP] 行情为空")
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

    # 计算市值
    rows = []
    total_mv = 0
    for p in positions:
        price = quote_map.get(p["code"])
        if price is None or price <= 0:
            continue
        mv = price * p["shares"]
        total_mv += mv
        rows.append({**p, "price": price, "mv": mv})

    total_asset = total_mv + cash

    # 单只超预算
    over_budget = [r for r in rows if r["budget"] > 0 and r["mv"] > r["budget"]]

    # 属性汇总
    attr_sum = {}
    for r in rows:
        if r["attr"] == "框架外":
            continue
        attr_sum.setdefault(r["attr"], 0)
        attr_sum[r["attr"]] += r["mv"]

    over_attr = []
    for attr, mv in attr_sum.items():
        cap = ATTR_CAP.get(attr, 0)
        if cap > 0 and mv > cap / 100 * total_asset:
            over_attr.append((attr, mv, cap))

    print(f"  单只超预算 {len(over_budget)} | 属性超上限 {len(over_attr)} | 总资产 {total_asset:.0f}")

    lines = [
        f"## 📊 持仓体检 {now:%m-%d %H:%M}",
        f"总资产{total_asset:.0f} · 现金{cash:.0f} · 单只超预算{len(over_budget)} · 属性超限{len(over_attr)}",
        "",
    ]

    if over_budget:
        lines.append("**🔴 单只超预算（市值>框架预算）**")
        lines.append("")
        for r in over_budget:
            times = r["mv"] / r["budget"]
            lines.append(f"· {r['name']}({r['code']}) 市值{r['mv']:.0f} 预算{r['budget']:.0f} 超{times:.1f}倍")
            lines.append("")

    if over_attr:
        lines.append("**🔴 属性超上限（六类七层）**")
        lines.append("")
        for attr, mv, cap in over_attr:
            pct = mv / total_asset * 100
            lines.append(f"· {attr} 合计{mv:.0f}元 占比{pct:.1f}% 上限{cap}%")
            lines.append("")

    lines.append("**📋 持仓仓位明细**")
    lines.append("")
    for r in rows:
        pct = r["mv"] / total_asset * 100
        if r["budget"] > 0 and r["mv"] > r["budget"]:
            mark = "🔴"
        else:
            mark = "🟢"
        budget_str = f" 预算{r['budget']:.0f}" if r["budget"] > 0 else ""
        lines.append(f"{mark} {r['name']}({r['code']}) {r['attr']} 市值{r['mv']:.0f} 占比{pct:.1f}%{budget_str}")
        lines.append("")

    lines.append("⚠️ 超预算/超限的是历史遗留仓位，逢反弹逐步降到框架线内，不再加仓超限标的。")

    push(f"📊 持仓体检（超预算{len(over_budget)}/超限{len(over_attr)}）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
