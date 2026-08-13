"""
股息收租 v1.1（任务⑤）
功能：持仓股股息日历 + 年度收租现金流
数据源：Tushare dividend（分红） + 东财现价
运行：收盘后 17:00
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone
import tushare as ts

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"
BATCH_SIZE = 20
EXCLUDE = {"002747"}


def to_tscode(code):
    if code.startswith(("6", "9")):
        return code + ".SH"
    return code + ".SZ"


def to_secid(code):
    if code.startswith(("6", "9")):
        return "1." + code
    return "0." + code


def load_holdings():
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}
    return {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}


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
    print(f"[START] 股息收租 {now:%m-%d %H:%M}")

    if not TUSHARE_TOKEN:
        print("[SKIP] 未配置 TUSHARE_TOKEN")
        return

    pro = ts.pro_api(TUSHARE_TOKEN)
    holdings = load_holdings()

    positions = []
    for code, info in holdings.items():
        if code in EXCLUDE:
            continue
        positions.append({
            "code": code,
            "name": info.get("name", code),
            "shares": info.get("shares", 0) or 0,
        })

    if not positions:
        push(f"📊 股息收租 {now:%m-%d}", "## 股息收租\n\n无持仓。")
        return

    secids = [to_secid(p["code"]) for p in positions]
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

    rows = []
    total_income = 0

    for p in positions:
        code = p["code"]
        tscode = to_tscode(code)
        name = p["name"]
        shares = p["shares"]
        price = quote_map.get(code, 0)

        cash_div = None
        ex_date = ""
        end_date = ""
        try:
            df = pro.dividend(ts_code=tscode)
            if df is not None and not df.empty:
                print(f"  {name} dividend原始{len(df)}行 列:{list(df.columns)}")
                # 只取有现金分红（每股派息>0）的
                df2 = df[df["cash_div"].notna() & (df["cash_div"] > 0)]
                if not df2.empty:
                    df2 = df2.sort_values("end_date")
                    row = df2.iloc[-1]
                    cash_div = float(row["cash_div"])
                    ex_date = str(row.get("ex_date", ""))[:10]
                    end_date = str(row.get("end_date", ""))[:4]
                else:
                    print(f"  {name} 无cash_div>0记录 原始值:{list(df['cash_div'].head())}")
        except Exception as e:
            print(f"  {name} 分红失败: {e}")
        time.sleep(0.3)

        if cash_div is None or cash_div <= 0:
            continue

        income = cash_div * shares
        yield_pct = cash_div / price * 100 if price > 0 else 0
        total_income += income

        rows.append({
            "name": name, "code": code, "shares": shares, "price": price,
            "cash_div": cash_div, "income": income, "yield_pct": yield_pct,
            "ex_date": ex_date, "end_date": end_date,
        })

    rows.sort(key=lambda x: -x["income"])

    print(f"  分红 {len(rows)} 只 | 年度收租 {total_income:.0f} 元")

    lines = [
        f"## 📊 股息收租 {now:%m-%d %H:%M}",
        f"持仓{len(positions)}只 · 有分红{len(rows)}只 · 年度收租约 {total_income:.0f} 元",
        "",
    ]

    if rows:
        lines.append("**💰 收租明细（按到手金额排序）**")
        lines.append("")
        for r in rows:
            ex = f" 除息{r['ex_date']}" if r["ex_date"] and r["ex_date"] != "nan" else ""
            lines.append(f"· {r['name']}({r['code']}) 每股{r['cash_div']:.2f}元 × {r['shares']}股 = {r['income']:.0f}元 股息率{r['yield_pct']:.1f}%{ex}")
            lines.append("")
    else:
        lines.append("⚠️ 暂无有效分红数据（见运行日志调试信息）")
        lines.append("")

    lines.append(f"💰 年度收租合计约 **{total_income:.0f} 元**（税前，未计持有期税率）")
    lines.append("")
    lines.append("⚠️ 收租是框架的底仓逻辑，股息是长期持有的保底现金流。")

    push(f"💰 股息收租（年{total_income:.0f}元）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
