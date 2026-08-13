"""
聪明钱联动哨兵 v1.2（任务⑦）
功能：持仓股+买入候选的主力资金流向（聪明钱信号）
数据源：Tushare moneyflow（个股资金流向）
联动：聪明钱流入+接近触发价=强买点；聪明钱流出持仓=警示
运行：收盘后 17:30
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone
import tushare as ts

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"
BATCH_SIZE = 20
GAP_LIMIT = 10.0
DAYS = 5
INFLOW_TH = 0.3     # 亿元（原3000万）
OUTFLOW_TH = 0.3    # 亿元（原3000万）
EXCLUDE = {"002747"}   # 埃斯顿（负成本，已了结）


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
        return {}, {}
    trigger = data.get("trigger", {})
    holdings = {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}
    return trigger, holdings


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


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 聪明钱哨兵 {now:%m-%d %H:%M}")

    if not TUSHARE_TOKEN:
        print("[SKIP] 未配置 TUSHARE_TOKEN")
        return

    pro = ts.pro_api(TUSHARE_TOKEN)
    trigger, holdings = load_framework()

    # 监控范围：持仓股（排除埃斯顿）+ gap≤10%的候选
    targets = {}
    for code, info in holdings.items():
        if code in EXCLUDE:
            continue
        targets[code] = {"name": info.get("name", code), "is_hold": True, "trigger": trigger.get(code, {}).get("trigger_price", 0) or 0}

    secids = [to_secid(c) for c in targets.keys()]
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

    for code, info in trigger.items():
        tp = info.get("trigger_price", 0) or 0
        if tp <= 0 or code in targets or code in EXCLUDE:
            continue
        price = quote_map.get(code, 0)
        if price > 0 and (price - tp) / tp * 100 <= GAP_LIMIT:
            targets[code] = {"name": info.get("name", code), "is_hold": False, "trigger": tp}

    end = (now - timedelta(days=1)).strftime("%Y%m%d")
    start = (now - timedelta(days=DAYS + 15)).strftime("%Y%m%d")

    inflow = []
    outflow = []

    for code, meta in targets.items():
        tscode = to_tscode(code)
        try:
            df = pro.moneyflow(ts_code=tscode, start_date=start, end_date=end,
                               fields='ts_code,trade_date,net_mf_amount')
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").tail(DAYS)
                net = df["net_mf_amount"].sum() / 10000   # 万元 → 亿元
                if net >= INFLOW_TH:
                    inflow.append((meta["name"], code, net, meta["is_hold"], meta["trigger"]))
                elif net <= -OUTFLOW_TH:
                    outflow.append((meta["name"], code, net, meta["is_hold"], meta["trigger"]))
        except Exception as e:
            print(f"  {meta['name']} 资金流失败: {e}")
        time.sleep(0.3)

    inflow.sort(key=lambda x: -x[2])
    outflow.sort(key=lambda x: x[2])

    print(f"  流入 {len(inflow)} | 流出 {len(outflow)}")

    lines = [
        f"## 📊 聪明钱哨兵 {now:%m-%d %H:%M}",
        f"监控{len(targets)}只 · 主力流入{len(inflow)} · 主力流出{len(outflow)}（近{DAYS}日）",
        "",
    ]

    if inflow:
        lines.append("**🟢 主力资金净流入（聪明钱在买）**")
        lines.append("")
        for name, code, net, is_hold, tp in inflow:
            tag = "持仓" if is_hold else "候选"
            trig = f" 触发{tp:.2f}" if tp > 0 else ""
            lines.append(f"· {name}({code}) 净流入{net:+.2f}亿 [{tag}]{trig}")
            lines.append("")

    if outflow:
        lines.append("**🔴 主力资金净流出（聪明钱在卖）**")
        lines.append("")
        for name, code, net, is_hold, tp in outflow:
            tag = "持仓⚠" if is_hold else "候选"
            lines.append(f"· {name}({code}) 净流出{net:+.2f}亿 [{tag}]")
            lines.append("")

    if not inflow and not outflow:
        lines.append("暂无主力资金异常信号。")
        lines.append("")

    lines.append("⚠️ 聪明钱信号是博弈参考，不是买卖依据。收租底仓为主，主力资金仅作情绪联动。")

    push(f"📊 聪明钱哨兵（流入{len(inflow)}/流出{len(outflow)}）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
