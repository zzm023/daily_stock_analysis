"""
触发价总监控 v1.7（任务①）
功能：已触发 + 买入候选 + 距触发价排行 + 建议仓位 + 持仓分层补仓
数据源：framework_state.json（触发价/持仓成本）+ attr_map.json（分类）+ 东财实时价
补仓规则：首次1万试仓，跌10%/20%/30%翻倍补(2/4/8万)，跌50%基本面OK才补拉成本，仓位上限约束
运行：收盘后 15:45
"""
import os, json, time, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"
ATTR_FILE = "attr_map.json"

GAP_CLOSE = 10.0
RANK_TOP = 10
BATCH_SIZE = 20
TOTAL_CAPITAL = 600000

POSITION_CAP = {
    "①永续债": 0.15, "②高息成长": 0.08, "③周期拐点": 0.03,
    "④全球寡头": 0.02, "⑤品牌心智": 0.08, "⑥小众冠军": 0.08, "科技✅⚠": 0.08,
}

# 分层补仓：跌幅阈值 + 翻倍金额（前三层），第4层补剩余拉成本
LAYERS = [
    (0.10, 20000, "第1层"),
    (0.20, 40000, "第2层"),
    (0.30, 80000, "第3层"),
    (0.50, None,  "第4层"),
]


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
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    all_diff = []
    for i in range(0, len(secids), BATCH_SIZE):
        batch = secids[i:i + BATCH_SIZE]
        for attempt in range(retries):
            try:
                r = requests.get(url, params={"secids": ",".join(batch), "fields": "f2,f12,f14"},
                                 headers=headers, timeout=30)
                r.raise_for_status()
                data = r.json()
                diff = data.get("data", {}).get("diff", [])
                if diff:
                    all_diff.extend(diff)
                    break
            except Exception as e:
                print(f"  [东财] 失败: {e}")
            time.sleep(3)
        time.sleep(2)
    return all_diff


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        r = requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title,
            "content": content, "template": "markdown", "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
        print(f"  [Push] {'OK' if r.json().get('code') == 200 else r.json()}")
    except Exception as e:
        print(f"  [Push] {e}")


def cap_line(attr):
    cap = POSITION_CAP.get(attr, 0)
    if cap <= 0:
        return ""
    amt = TOTAL_CAPITAL * cap / 10000
    return f"  💰 建议仓位 {attr} ≤{cap*100:.0f}%（约{amt:.0f}万）"


def layer_advice(cost, shares, price, attr):
    """分层补仓建议：返回 (层数, 建议金额, 是否超标) 或 None"""
    if cost <= 0 or price <= 0:
        return None
    drop = (price - cost) / cost
    if drop > -0.10:
        return None

    # 判断处于哪一层（最深）
    layer = 0
    for i, (thr, _, _) in enumerate(LAYERS):
        if drop <= -thr:
            layer = i + 1
        else:
            break

    cap = POSITION_CAP.get(attr, 0)
    cap_amt = TOTAL_CAPITAL * cap
    invested = cost * shares
    remain = cap_amt - invested  # 剩余可补额度

    if remain <= 0:
        return (layer, 0, True)  # 已超上限，停止

    if layer == 4:
        amt = remain  # 第4层：补剩余，拉低成本
    else:
        amt = min(LAYERS[layer - 1][1], remain)
    return (layer, amt, False)


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 触发价总监控 v1.7 {now:%m-%d %H:%M}")

    trigger, holdings = load_framework()
    attr_map = load_attr_map()
    hold_codes = set(holdings.keys())

    candidates = []
    for code, info in trigger.items():
        tp = info.get("trigger_price", 0) or 0
        if tp <= 0:
            continue
        candidates.append({
            "code": code, "name": info.get("name", code),
            "trigger": tp, "is_hold": code in hold_codes,
        })

    # 持仓股也要拉价（补仓提醒），并入 secids
    hold_secids = [to_secid(c) for c in holdings if c not in {x["code"] for x in candidates}]
    secids = [to_secid(c["code"]) for c in candidates] + hold_secids

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

    hit, close, ranking = [], [], []
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

    # 持仓分层补仓
    layers = []
    for code, h in holdings.items():
        price = quote_map.get(code)
        if price is None or price <= 0:
            continue
        try:
            cost = float(h.get("cost", 0))
            shares = float(h.get("shares", 0))
        except:
            continue
        attr = attr_map.get(code, "")
        adv = layer_advice(cost, shares, price, attr)
        if adv:
            layers.append({
                "code": code, "name": h.get("name", code),
                "cost": cost, "price": price, "shares": shares,
                "layer": adv[0], "amt": adv[1], "over": adv[2], "attr": attr,
            })
    layers.sort(key=lambda x: -x["layer"])

    print(f"  已触发 {len(hit)} | 候选 {len(close)} | 补仓层 {len(layers)}")

    lines = [
        f"## 📊 触发价总监控 {now:%m-%d %H:%M}",
        f"监控{len(candidates)}只 · 触发{len(hit)} · 候选{len(close)} · 补仓{len(layers)}",
        "",
    ]

    if layers:
        lines.append("**🔻 持仓补仓提醒（跌10%起，翻倍补，超标停）**")
        lines.append("")
        for r in layers:
            drop = (r["price"] - r["cost"]) / r["cost"] * 100
            if r["over"]:
                lines.append(f"· {r['name']}({r['code']}) 现{r['price']:.2f} 成本{r['cost']:.2f}（{drop:.0f}%）⚠️已超{r['attr']}上限，停止补仓")
            else:
                tag = "【拉成本·确认基本面未恶化】" if r["layer"] == 4 else f"补{r['amt']/10000:.0f}万"
                lines.append(f"· {r['name']}({r['code']}) 现{r['price']:.2f} 成本{r['cost']:.2f}（{drop:.0f}%）→ {LAYERS[r['layer']-1][2]} {tag}")
            lines.append("")
    else:
        lines.append("无持仓进入补仓区（跌幅<10%或未持仓）")
        lines.append("")

    if hit:
        lines.append("**🔥 已触发（现价≤触发价）**")
        lines.append("")
        for r in hit:
            tag = "｜补仓" if r["is_hold"] else "｜待买"
            lines.append(f"· {r['name']}({r['code']}) {r['price']:.2f}→{r['trigger']:.2f} 距{r['gap']:+.1f}%{tag}")
            cl = cap_line(attr_map.get(r["code"], ""))
            if cl:
                lines.append(cl)
            lines.append("")

    if close:
        lines.append("**🎯 买入候选（距触发≤10%，估值待共振确认）**")
        lines.append("")
        for r in close:
            lines.append(f"· {r['name']}({r['code']}) {r['price']:.2f}→{r['trigger']:.2f} 距{r['gap']:+.1f}%")
            cl = cap_line(attr_map.get(r["code"], ""))
            if cl:
                lines.append(cl)
            lines.append("")

    if ranking:
        lines.append(f"**📉 距触发价排行（前{RANK_TOP}）**")
        lines.append("")
        for i, r in enumerate(ranking[:RANK_TOP], 1):
            lines.append(f"{i}. {r['name']} {r['price']:.2f}→{r['trigger']:.2f}（{r['gap']:+.1f}%）")
            lines.append("")

    lines.append("⚠️ 候选仅看gap，PE/PB共振由「估值共振」确认。补仓规则：跌10%/20%/30%翻倍补，跌50%基本面OK才补，超标即停。")

    push(f"📊 触发价监控（{len(hit)}触发/{len(close)}候选/{len(layers)}补仓）", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
