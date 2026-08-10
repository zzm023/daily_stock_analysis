"""
压力测试 v2
修复：亏损从大到小排列 / 每行一个属性
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

BETA = {
    "①永续债":0.6,"②高息成长":0.8,"③周期拐点":1.4,
    "④全球寡头":1.0,"⑤品牌心智":0.9,"⑥小众冠军":1.1,
    "科技⚠":1.5,"未分类":1.0,
}

SCENARIOS = [(-20, -0.20), (-30, -0.30), (-40, -0.40)]


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
    print(f"[START] 压力测试 v2 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    cash = hold.get("cash", 0)
    codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]
    prices = batch_prices(codes)

    total_cost = 0
    total_mv = 0
    positions = []
    for code in codes:
        v = hold[code]
        if not isinstance(v, dict):
            continue
        name = v.get("name", code)
        cost = v.get("cost", 0) if v.get("cost", 0) > 0 else 0
        shares = v.get("shares", 0)
        price = prices.get(code, 0)
        mv = price * shares if price else cost * shares
        total_cost += cost * shares
        total_mv += mv
        a = ATTR.get(code, "未分类")
        positions.append((name, mv, a, BETA.get(a, 1.0)))

    total_asset = total_mv + cash

    lines = [
        f"压力测试 {now:%m}.{now:%d}",
        f"总{total_asset/10000:.0f}万 仓{total_mv/10000:.0f} 现{cash/10000:.0f}万",
    ]

    for label, pct in SCENARIOS:
        loss = 0
        attr_loss = {}
        for _, mv, a, beta in positions:
            sl = mv * pct * beta
            loss += sl
            attr_loss[a] = attr_loss.get(a, 0) + sl

        post = total_asset + loss
        post_pnl = (total_mv + loss) - total_cost

        lines.append("")
        lines.append(f"[{label}%] 总→{post/10000:.0f}万 亏{abs(loss)/10000:.1f}万 ({loss/total_asset*100:.1f}%)")
        lines.append(f"浮动→{post_pnl/10000:+.1f}万")
        lines.append("")

        sorted_attr = sorted(attr_loss.items(), key=lambda x: x[1])  # 亏损多的排前
        for a, l in sorted_attr[:5]:
            if l < -0.01:
                lines.append(f"  - {a} 亏{abs(l)/10000:.1f}万")
            else:
                lines.append(f"  - {a} 无变化")
        lines.append("")

    lines.append(f"> β 永续0.6 高息0.8 品牌0.9 寡头1.0 小众1.1 周期1.4 科技1.5")

    push(f"压力测试 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
