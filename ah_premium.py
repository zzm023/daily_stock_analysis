"""
AH溢价监控 v3
修复：去无效H对 + 港币汇率换算 + 核实海天
"""
import os
import json
import requests
import re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# A股 → H股
AH_PAIRS = {
    "600031": "hk06031",  # 三一重工
    "601601": "hk02601",  # 中国太保
    "600585": "hk00914",  # 海螺水泥
    "600188": "hk01171",  # 兖矿能源
    "600660": "hk03606",  # 福耀玻璃
    "600036": "hk03968",  # 招商银行
    "600941": "hk00941",  # 中国移动
    "000333": "hk00300",  # 美的集团
    "688187": "hk03898",  # 时代电气
    "603288": "hk03288",  # 海天味业
}


def get_hkd_cny():
    """汇率：港币兑人民币"""
    try:
        r = requests.get("http://qt.gtimg.cn/q=fx_hkdcny", timeout=10)
        r.encoding = "gbk"
        m = re.search(r'v_fx_hkdcny="[^"]*"', r.text)
        if m:
            parts = m.group().split("~")
            if len(parts) >= 4 and parts[3]:
                return float(parts[3]) / 100
    except Exception:
        pass
    return 0.92  # 兜底


def batch_prices(pairs):
    """腾讯批量取 A+H"""
    results = {}
    all_ids = []
    for a, h in pairs.items():
        a_sid = f"sh{a}" if a.startswith("6") else f"sz{a}"
        all_ids.append(a_sid)
        all_ids.append(h)

    for i in range(0, len(all_ids), 40):
        batch = all_ids[i:i + 40]
        symbols = ",".join(batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for sid in batch:
                m = re.search(f"v_{sid}=\"[^\"]*\"", r.text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 4:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    name = parts[1] if len(parts) > 1 else sid
                    if price and price > 0:
                        results[sid] = {"price": price, "name": name}
                except Exception:
                    pass
        except Exception:
            pass
    return results


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
    print(f"[START] AH溢价监控 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    active = {}
    for a_code, h_code in AH_PAIRS.items():
        if a_code in trigger:
            active[a_code] = h_code

    fx = get_hkd_cny()
    print(f"  港币/人民币 = {fx:.4f}")

    quotes = batch_prices(active)
    print(f"  行情 {len(quotes)} 条")

    held_skip = []
    suggest_h = []
    normal = []

    for a_code, h_code in active.items():
        a_sid = f"sh{a_code}" if a_code.startswith("6") else f"sz{a_code}"
        a_q = quotes.get(a_sid)
        h_q = quotes.get(h_code)
        if not a_q or not h_q:
            continue

        a_price = a_q["price"]       # 人民币
        h_price_hkd = h_q["price"]   # 港币
        h_price_cny = h_price_hkd * fx  # 换算人民币

        premium = (a_price - h_price_cny) / h_price_cny * 100

        t = trigger.get(a_code, {})
        name = t.get("name", a_code) if isinstance(t, dict) else a_code
        is_held = a_code in hold

        if is_held:
            held_skip.append(name)
        elif premium > 50:
            suggest_h.append({
                "name": name, "a_price": a_price,
                "h_price_hkd": h_price_hkd, "h_price_cny": h_price_cny,
                "premium": premium,
            })
        else:
            normal.append({
                "name": name, "a_price": a_price,
                "h_price_hkd": h_price_hkd, "h_price_cny": h_price_cny,
                "premium": premium,
            })

    lines = [
        f"AH溢价 {now:%m}.{now:%d}",
        f"港币汇率 {fx:.4f} | H股已换算人民币",
        f"框架内{len(active)}对",
    ]

    if held_skip:
        lines.append("")
        lines.append(f"持仓跳过 {len(held_skip)}只")
        lines.append(f"  {', '.join(held_skip)}")

    if suggest_h:
        lines.append("")
        lines.append(f"🔄 溢价>50% 买H更划算（{len(suggest_h)}只）")
        for r in suggest_h:
            lines.append(
                f"- {r['name']} A¥{r['a_price']:.2f} "
                f"H HK${r['h_price_hkd']:.2f}(≈¥{r['h_price_cny']:.2f}) "
                f"溢价{r['premium']:+.0f}%"
            )

    if normal:
        lines.append("")
        lines.append(f"溢价≤50%（{len(normal)}只）")
        for r in normal:
            lines.append(
                f"- {r['name']} A¥{r['a_price']:.2f} "
                f"H HK${r['h_price_hkd']:.2f}(≈¥{r['h_price_cny']:.2f}) "
                f"溢价{r['premium']:+.0f}%"
            )

    push(f"AH溢价 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
