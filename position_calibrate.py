"""
仓位校准器 v2
修复：- 列表强制 pushplus 分行
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

ATTR = {
    "600036":"①永续债","601601":"①永续债","600018":"①永续债",
    "601816":"①永续债","600900":"①永续债","600941":"①永续债",
    "000429":"①永续债","600007":"①永续债",
    "600188":"②高息成长","600585":"②高息成长","300498":"②高息成长",
    "603568":"②高息成长","600598":"②高息成长",
    "000792":"③周期拐点","600299":"③周期拐点","002601":"③周期拐点",
    "603806":"③周期拐点",
    "600309":"④全球寡头","600660":"④全球寡头","601058":"④全球寡头",
    "600406":"④全球寡头","000651":"④全球寡头","000333":"④全球寡头",
    "300124":"④全球寡头",
    "000538":"⑤品牌心智","603605":"⑤品牌心智","605098":"⑤品牌心智",
    "600298":"⑤品牌心智","603288":"⑤品牌心智","002027":"⑤品牌心智",
    "600690":"⑤品牌心智",
    "002508":"⑥小众冠军","002032":"⑥小众冠军","002884":"⑥小众冠军",
    "002318":"⑥小众冠军","603855":"⑥小众冠军","603508":"⑥小众冠军",
    "300628":"⑥小众冠军","000708":"⑥小众冠军","000157":"⑥小众冠军",
    "600031":"⑥小众冠军","600761":"⑥小众冠军","600066":"⑥小众冠军",
    "600486":"⑥小众冠军",
    "688187":"科技⚠","300832":"科技⚠","002837":"科技⚠",
    "300627":"科技⚠","002410":"科技⚠","600845":"科技⚠",
    "002747":"科技⚠","600161":"科技⚠",
}

CAPS = {
    "①永续债":0.15,"②高息成长":0.08,"③周期拐点":0.03,
    "④全球寡头":0.02,"⑤品牌心智":0.08,"⑥小众冠军":0.08,
    "科技⚠":0.08,
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
    print(f"[START] 仓位校准 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    total_capital = state.get("meta", {}).get("total_capital", 600000)
    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(hold_codes)

    attr_mv = {}
    attr_stocks = {}
    for code in hold_codes:
        v = hold[code]
        if not isinstance(v, dict):
            continue
        name = v.get("name", code)
        price = prices.get(code, 0)
        shares = v.get("shares", 0)
        cost = v.get("cost", 0)
        mv = price * shares if price else (cost * shares if cost > 0 else 0)
        a = ATTR.get(code, "未分类")
        attr_mv[a] = attr_mv.get(a, 0) + mv
        attr_stocks.setdefault(a, []).append(f"{name} {mv/10000:.1f}万")

    total_mv = sum(attr_mv.values())

    lines = [
        f"仓位校准 {now:%m}.{now:%d}",
        f"资金{total_capital/10000:.0f}万 | 持仓{total_mv/10000:.0f}万 | 仓位{total_mv/total_capital*100:.0f}%",
    ]

    over = []
    empty = []
    ok = []

    for a, cap_pct in sorted(CAPS.items(), key=lambda x: x[1], reverse=True):
        cap = total_capital * cap_pct
        used = attr_mv.get(a, 0)
        pct_used = used / cap * 100 if cap else 0
        gap = cap - used

        if pct_used > 100:
            over.append(f"- ⚠️ **{a}** 超{abs(gap)/10000:.1f}万 上限{cap/10000:.0f}→实际{used/10000:.1f}万 {pct_used:.0f}%")
            for s in attr_stocks.get(a, []):
                over.append(f"    - {s}")
        elif pct_used < 10 and gap > 10000:
            empty.append(f"- ○ **{a}** 上限{cap/10000:.0f}万 未配置")
        else:
            ok.append(f"- ✓ **{a}** 上限{cap/10000:.0f}万 实际{used/10000:.1f}万 {pct_used:.0f}%")
            for s in attr_stocks.get(a, []):
                ok.append(f"    - {s}")

    if over:
        lines.append("")
        lines.append("超限")
        lines.extend(over)
    if empty:
        lines.append("")
        lines.append("空缺")
        lines.extend(empty)
    if ok:
        lines.append("")
        lines.append("正常")
        lines.extend(ok)
    lines.append("")

    push(f"仓位校准 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
