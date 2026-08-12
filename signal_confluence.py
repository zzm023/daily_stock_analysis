"""
多信号共振 v3 - Tushare+兜底
"""
import os, json, requests, re, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

GROWTH_FB = {
    "600036": 1.2, "601601": 64.9, "600031": 27.4,
    "600585": -26.0, "600188": 8.5, "600660": 25.0,
    "600941": 5.2, "000333": 14.3, "688187": 24.8,
    "603288": -18.0, "600900": 7.3, "000651": 10.2,
    "002601": 45.0, "600161": 46.5, "300498": 110.0,
    "600690": 12.8, "000157": 41.5, "002747": -20.0,
    "600018": 5.0, "600598": 8.0, "603568": 10.0,
    "600007": 8.0, "000429": 6.0, "000792": -40.0,
    "600299": 25.0, "600066": 15.0, "600761": 15.0,
    "601058": 30.0, "600486": -5.0, "603806": -15.0,
    "000538": 5.0, "603605": 15.0, "605098": 10.0,
    "600298": -8.0, "300628": 8.0, "002508": 3.0,
    "002032": 12.0, "002884": 10.0, "002318": 15.0,
    "603855": 10.0, "603508": 12.0, "300832": 12.0,
    "002837": 20.0, "300627": 12.0, "002410": -5.0,
    "300124": -10.0, "600309": -8.0, "688036": 10.0,
    "605117": 15.0, "603298": 5.0, "603699": 8.0,
    "002372": 5.0, "601816": 3.0, "002475": 20.0,
    "600406": 10.0, "600845": -3.5,
}

DIV_FB = {
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
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if not m: continue
                parts = m.group().split("~")
                if len(parts) < 48: continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    if price: results[c] = {"price": price, "pe": pe}
                except: pass
        except: pass
    return results


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
    print(f"[START] 信号共振 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    quotes = batch_tencent(codes)

    # ── Tushare ──
    growth = {}
    try:
        from tushare_data import get_profit_growth, auto_whitelist
        auto_whitelist()
        growth = get_profit_growth(codes)
        print(f"  Tushare {len(growth)}只")
    except Exception as e:
        print(f"  Tushare失败: {e}")

    scored = []
    for code in codes:
        t = trigger[code]
        name = t.get("name", code)
        tp = t.get("trigger_price", 0)
        tag = t.get("tag", "")

        q = quotes.get(code, {})
        price = q.get("price")
        pe = q.get("pe")
        if not price: continue

        lights = []
        if pe is not None and pe < 15: lights.append("PE")
        elif pe is None: lights.append("PE?")

        dist_pct = None
        if tp > 0:
            dist_pct = (price - tp) / tp * 100
            if dist_pct <= 10: lights.append("触发")

        profit = growth.get(code) or GROWTH_FB.get(code)
        if profit is not None and profit > 0: lights.append("利润")

        dps = DIV_FB.get(code, 0)
        div_yield = None
        if dps > 0:
            div_yield = dps / price * 100
            if div_yield > 3: lights.append("股息")

        n = len([l for l in lights if l != "PE?"])
        scored.append({
            "name": name, "price": price, "lights": lights, "n": n,
            "held": code in hold, "tag": tag, "dist_pct": dist_pct,
        })

    strong = [s for s in scored if s["n"] >= 3]
    strong.sort(key=lambda x: x["n"], reverse=True)

    lines = [f"信号共振 {now:%m}.{now:%d}", "4灯: PE低估 | 近触发 | 利润+ | 高股息"]
    if strong:
        lines.append("")
        lines.append(f"🔥 3灯以上（{len(strong)}只）")
        for s in strong:
            h = "★" if s["held"] else ""
            ls = " ".join(s["lights"])
            lines.append(f"- {h}{s['name']} {s['price']:.2f} [{ls}] {s['tag']}")
    else:
        lines.append(""); lines.append("无3灯以上个股  不在共振区")

    medium = [s for s in scored if s["n"] == 2]
    medium.sort(key=lambda x: x.get("dist_pct", 999) or 999)
    if medium:
        lines.append("")
        lines.append(f"🟡 2灯观察（{len(medium)}只）")
        for s in medium[:8]:
            h = "★" if s["held"] else ""
            ls = " ".join(s["lights"])
            lines.append(f"- {h}{s['name']} {s['price']:.2f} [{ls}]")
        if len(medium) > 8: lines.append(f"- ...等{len(medium)-8}只")

    lines.append("")
    lines.append(f"> 共{len(scored)}只 | Tushare+兜底")

    push(f"信号共振 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 3灯{len(strong)}只 2灯{len(medium)}只")


if __name__ == "__main__":
    main()
