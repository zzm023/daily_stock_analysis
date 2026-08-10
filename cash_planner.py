"""
现金规划器 v1
按框架属性分配现金：每类上限 / 已用 / 剩余 / 可买
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 框架股 → 属性
ATTR = {
    "600036": "①永续债", "601601": "①永续债", "600018": "①永续债",
    "601816": "①永续债", "600900": "①永续债", "600941": "①永续债",
    "000429": "①永续债", "600007": "①永续债",
    "600188": "②高息成长", "600585": "②高息成长", "300498": "②高息成长",
    "603568": "②高息成长", "600598": "②高息成长",
    "000792": "③周期拐点", "600299": "③周期拐点", "002601": "③周期拐点",
    "603806": "③周期拐点",
    "600309": "④全球寡头", "600660": "④全球寡头", "601058": "④全球寡头",
    "600406": "④全球寡头", "000651": "④全球寡头", "000333": "④全球寡头",
    "300124": "④全球寡头",
    "000538": "⑤品牌心智", "603605": "⑤品牌心智", "605098": "⑤品牌心智",
    "600298": "⑤品牌心智", "603288": "⑤品牌心智", "002027": "⑤品牌心智",
    "600690": "⑤品牌心智",
    "002508": "⑥小众冠军", "002032": "⑥小众冠军", "002884": "⑥小众冠军",
    "002318": "⑥小众冠军", "603855": "⑥小众冠军", "603508": "⑥小众冠军",
    "300628": "⑥小众冠军", "000708": "⑥小众冠军", "000157": "⑥小众冠军",
    "600031": "⑥小众冠军", "600761": "⑥小众冠军", "600066": "⑥小众冠军",
    "600486": "⑥小众冠军",
    "688187": "科技⚠", "300832": "科技⚠", "002837": "科技⚠",
    "300627": "科技⚠", "002410": "科技⚠", "600845": "科技⚠",
    "002747": "科技⚠", "600161": "科技⚠",
}

CAPS = {
    "①永续债": 0.15, "②高息成长": 0.08, "③周期拐点": 0.03,
    "④全球寡头": 0.02, "⑤品牌心智": 0.08, "⑥小众冠军": 0.08,
    "科技⚠": 0.08,
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
    print(f"[START] 现金规划器 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    total_capital = state.get("meta", {}).get("total_capital", 600000)
    cash = hold.get("cash", total_capital * 0.5)

    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(hold_codes)

    attr_mv = {}
    for code in hold_codes:
        v = hold[code]
        if not isinstance(v, dict):
            continue
        price = prices.get(code, 0)
        shares = v.get("shares", 0)
        mv = price * shares if price else v.get("cost", 0) * shares
        attr = ATTR.get(code, "未分类")
        attr_mv[attr] = attr_mv.get(attr, 0) + mv

    total_mv = sum(attr_mv.values())
    total_asset = total_mv + cash

    lines = [
        f"现金规划 {now:%m}.{now:%d}",
        f"总{total_asset/10000:.0f}万 仓{total_mv/10000:.0f} 现{cash/10000:.0f}万",
        "",
    ]

    for attr, cap_pct in sorted(CAPS.items(), key=lambda x: x[1], reverse=True):
        cap = total_capital * cap_pct
        used = attr_mv.get(attr, 0)
        remain = cap - used
        pct_used = used / cap * 100 if cap else 0
        bar = "#" * int(pct_used / 10) + "-" * (10 - int(pct_used / 10))
        status = "满仓" if remain <= 0 else f"余{remain/10000:.1f}万"

        lines.append(f"{attr} 上限{cap/10000:.0f}万 {bar} {pct_used:.0f}% {status}")

    lines.append("")
    lines.append("未持仓类可用现金")
    for attr, cap_pct in CAPS.items():
        if attr in attr_mv and attr_mv[attr] > 0:
            continue
        cap = total_capital * cap_pct
        lines.append(f"  {attr}：{cap/10000:.1f}万")

    lines.append("")
    lines.append(f"> 现金占总{cash/total_asset*100:.0f}% | 等击球点")

    push(f"现金规划 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
