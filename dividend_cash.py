"""
分红金额预测 v3 - Tushare
"""
import os, json, requests, re, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

DIV_FB = {
    "002027": 0.33, "600690": 0.38, "000708": 0.55,
    "600845": 0.50, "000157": 0.16, "002601": 0.40,
    "600161": 0.05, "300498": 0.20, "002747": 0.00,
    "600036": 1.97, "601601": 1.02, "600031": 0.39,
    "600585": 1.48, "600188": 1.49, "600660": 1.30,
    "600941": 4.80, "000333": 3.00, "688187": 1.55,
    "603288": 0.75, "600900": 0.82, "601816": 0.12,
    "000651": 2.38, "300124": 0.50, "600309": 3.75,
}


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title, "content": content,
            "template": "markdown", "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
    except: pass


def main():
    now = datetime.now()
    print(f"[START] 分红预测 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]

    # Tushare
    divs = {}
    try:
        from tushare_data import get_dividends, auto_whitelist
        auto_whitelist()
        divs = get_dividends(hold_codes)
        print(f"  Tushare 分红 {len(divs)}只")
    except Exception as e:
        print(f"  Tushare失败: {e}")

    total = 0
    lines = [f"分红预测 {now:%m}.{now:%d}"]

    for code in hold_codes:
        v = hold[code]
        name = v.get("name", code)
        shares = v.get("shares", 0)

        dps = divs.get(code) or DIV_FB.get(code, 0)
        cash = shares * dps
        total += cash

        src = "T" if code in divs else "兜"
        lines.append(f"- {name} ×{shares}股  DPS{dps:.2f} = {cash/10000:.2f}万 [{src}]")

    lines.append("")
    lines.append(f"💵 合计 {total/10000:.2f}万")
    lines.append("> T=Tushare 兜=手工兜底")

    push(f"分红预测 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 合计{total/10000:.2f}万")


if __name__ == "__main__":
    main()
