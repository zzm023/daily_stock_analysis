"""
股息复利推演 v2
修复：差额单位 + 显示所有持仓
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

REF_YIELD = {
    "600036":5.5,"601601":4.5,"600018":3.0,"601816":2.5,
    "600900":3.5,"600941":4.0,"600406":2.0,"600598":2.5,
    "603568":3.0,"600007":3.5,"000429":5.0,"000157":3.5,
    "600585":5.5,"000792":0.0,"600188":6.0,"002601":4.0,
    "600299":1.5,"300498":0.0,"000651":6.0,"600066":5.0,
    "000333":4.0,"600690":3.0,"600031":3.5,"600309":3.0,
    "600660":3.5,"600761":3.0,"600486":2.5,"601058":2.0,
    "603806":1.0,"000708":4.0,"002027":5.0,"000538":3.5,
    "605098":4.0,"600298":2.0,"300628":3.5,
    "002508":5.5,"002884":4.0,"002318":4.0,
    "603855":3.0,"603508":3.5,"600161":1.0,"300832":1.0,
    "688187":1.0,"300124":1.5,"002837":0.5,"300627":1.0,
    "002410":0.5,"002747":0.5,"600845":1.0,
}


def batch_prices(codes):
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            text = r.text
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", text)
                if m:
                    parts = m.group().split("~")
                    if len(parts) >= 4 and parts[3]:
                        prices[c] = float(parts[3])
        except:
            pass
    return prices


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 股息复利推演 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    cash = hold.get("cash", 0)

    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(hold_codes)

    rows = []
    total_mv = 0
    total_yearly = 0

    for code in hold_codes:
        v = hold[code]
        if not isinstance(v, dict):
            continue
        name = v.get("name", code)
        price = prices.get(code, 0)
        shares = v.get("shares", 0)
        mv = price * shares if price else v.get("cost", 0) * shares
        if mv <= 0:
            continue
        total_mv += mv

        div_pct = REF_YIELD.get(code, 0)
        yearly = mv * div_pct / 100
        total_yearly += yearly

        c10 = mv * ((1 + div_pct/100) ** 10) if div_pct > 0 else mv
        c20 = mv * ((1 + div_pct/100) ** 20) if div_pct > 0 else mv

        rows.append({
            "name": name, "mv": mv, "yield": div_pct,
            "yearly": yearly, "c10": c10, "c20": c20,
        })

    rows.sort(key=lambda x: x["yearly"], reverse=True)

    total_c10 = sum(r["c10"] for r in rows)
    total_c20 = sum(r["c20"] for r in rows)
    gain_10 = (total_c10 - total_mv) / 10000
    gain_20 = (total_c20 - total_mv) / 10000

    lines = [
        f"股息复利推演 {now:%m}.{now:%d}",
        f"持仓{total_mv/10000:.0f}万 | 年收租{total_yearly/10000:.2f}万 | 息率{total_yearly/total_mv*100:.1f}%",
        "",
    ]

    lines.append("各股年收租")
    for r in rows:
        if r["yield"] > 0:
            lines.append(f"  - {r['name']} {r['mv']/10000:.1f}万 × {r['yield']:.1f}% = {r['yearly']/10000:.2f}万/年")
        else:
            lines.append(f"  - {r['name']} {r['mv']/10000:.1f}万 无分红（周期股）")

    lines.append("")
    lines.append(f"10年复利再投 → {total_c10/10000:.0f}万（+{gain_10:.1f}万）")
    lines.append(f"20年复利再投 → {total_c20/10000:.0f}万（+{gain_20:.1f}万）")

    if cash > 0:
        cash_10 = cash * 1.40
        cash_20 = cash * 1.99
        lines.append("")
        lines.append(f"含现金：10年{(total_c10+cash_10)/10000:.0f}万 20年{(total_c20+cash_20)/10000:.0f}万")

    lines.append("")
    lines.append(f"> 参考股息率 | 复利=股息再投")

    push(f"股息复利推演 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 年收租{total_yearly/10000:.2f}万")


if __name__ == "__main__":
    main()
