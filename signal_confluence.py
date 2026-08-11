"""
多信号共振 v1
4灯：PE低估 + 近触发价 + 利润正增长 + 高股息
3灯以上推送强信号
"""
import os
import json
import requests
import re
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 股息兜底
DIV_FALLBACK = {
    "002027": 0.33, "600690": 0.38, "000708": 0.55,
    "600845": 0.50, "000157": 0.16, "002601": 0.40,
    "600161": 0.05, "300498": 0.20, "002747": 0.00,
    "600036": 1.97, "601601": 1.02, "600031": 0.39,
    "600585": 1.48, "600188": 1.49, "600660": 1.30,
    "600941": 4.80, "000333": 3.00, "688187": 1.55,
    "603288": 0.75, "600900": 0.82, "601816": 0.12,
    "000651": 2.38, "300124": 0.50, "600309": 3.75,
    "605117": 0.80, "603298": 0.30, "002475": 0.20,
    "688036": 0.50, "603806": 0.30, "002508": 0.50,
    "603699": 0.30, "002372": 0.22, "300627": 0.30,
    "600299": 0.20, "600298": 0.30, "600486": 0.50,
}


def batch_tencent(codes):
    results = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i + 30]
        symbols = ",".join(
            f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch
        )
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 48:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    if price:
                        results[c] = {"price": price, "pe": pe}
                except Exception:
                    pass
        except Exception:
            pass
    return results


def get_growth(code):
    prefix = "1" if code.startswith("6") else "0"
    for attempt in range(2):
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={"secid": f"{prefix}.{code}", "fields": "f43,f173,f185"},
                timeout=15,
                headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}
            )
            d = r.json().get("data")
            if d and d.get("f43"):
                return {"profit_yoy": d.get("f185")}
        except Exception:
            pass
        time.sleep(1)
    return None


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        requests.post(
            "http://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown",
                "topic": PUSHPLUS_TOPIC,
            },
            timeout=10
        )
    except Exception:
        pass


def main():
    now = datetime.now()
    print(f"[START] 多信号共振 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    quotes = batch_tencent(codes)
    print(f"  行情 {len(quotes)} 只")

    scored = []
    for code in codes:
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        tag = t.get("tag", "")

        q = quotes.get(code, {})
        price = q.get("price")
        pe = q.get("pe")
        if not price:
            continue

        lights = []
        details = {}

        # 灯1: PE低估 (PE<15 或 未获取)
        if pe is not None and pe < 15:
            lights.append("PE")
            details["pe"] = f"{pe:.0f}"
        elif pe is None:
            lights.append("PE?")
            details["pe"] = "?"

        # 灯2: 近触发价 (距<10%)
        if tp > 0:
            dist = (price - tp) / tp * 100
            if dist <= 10:
                lights.append("触发")
                details["dist"] = f"{dist:+.0f}%"
            details["_dist"] = dist

        # 灯3: 利润正增长
        g = get_growth(code)
        profit = g.get("profit_yoy") if g else None
        if profit is not None and profit > 0:
            lights.append("利润")
            details["profit"] = f"{profit:+.0f}%"

        # 灯4: 高股息 (>3%)
        dps = DIV_FALLBACK.get(code, 0)
        if dps > 0:
            div_y = dps / price * 100
            if div_y > 3:
                lights.append("股息")
                details["div"] = f"{div_y:.1f}%"

        n = len([l for l in lights if l not in ("PE?",)])
        details["lights"] = lights
        details["n"] = n
        details["name"] = name
        details["price"] = price
        details["held"] = code in hold
        details["tag"] = tag

        scored.append(details)

    # 筛选 3灯以上
    strong = [s for s in scored if s["n"] >= 3]
    strong.sort(key=lambda x: x["n"], reverse=True)

    lines = [
        f"信号共振 {now:%m}.{now:%d}",
        f"4灯模型: PE低估 | 近触发 | 利润+ | 高股息",
    ]

    if strong:
        lines.append("")
        lines.append(f"🔥 3灯以上（{len(strong)}只）")
        for s in strong:
            h = "★" if s["held"] else ""
            lights_str = " ".join(s["lights"])
            lines.append(
                f"- {h}{s['name']} {s['price']:.2f} "
                f"[{lights_str}] {s['tag']}"
            )
    else:
        lines.append("")
        lines.append("无3灯以上个股  市场不在共振区")

    # 2灯备选
    medium = [s for s in scored if s["n"] == 2]
    medium.sort(key=lambda x: x.get("_dist", 999))
    if medium:
        lines.append("")
        lines.append(f"🟡 2灯观察（{len(medium)}只）")
        for s in medium[:8]:
            h = "★" if s["held"] else ""
            lights_str = " ".join(s["lights"])
            lines.append(f"- {h}{s['name']} {s['price']:.2f} [{lights_str}]")
        if len(medium) > 8:
            lines.append(f"- ...等{len(medium)-8}只")

    total = len(scored)
    lines.append("")
    lines.append(f"> 共扫描{total}只 | 3灯以上=击球区")

    push(f"信号共振 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 3灯{len(strong)}只 2灯{len(medium) if 'medium' in dir() else 0}")


if __name__ == "__main__":
    main()
