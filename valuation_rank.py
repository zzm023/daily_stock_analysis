"""
估值分位数 v1
腾讯批量 → PE/PB 全框架排名 → 谁最便宜谁最贵
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 属性标签
ATTR = {
    "600036":"①永续债","601601":"①永续债","600018":"①永续债",
    "601816":"①永续债","600900":"①永续债","600941":"①永续债",
    "000429":"①永续债","600007":"①永续债",
    "600188":"②高息成长","600585":"②高息成长","300498":"②高息成长",
    "603568":"②高息成长","600598":"②高息成长",
    "000792":"③周期拐点","600299":"③周期拐点","002601":"③周期拐点","600096":"③周期拐点",
    "603806":"③周期拐点",
    "600309":"④全球寡头","600660":"④全球寡头","601058":"④全球寡头",
    "600406":"④全球寡头","000651":"④全球寡头","000333":"④全球寡头",
    "300124":"④全球寡头",
    "000538":"⑤品牌心智","605098":"⑤品牌心智",
    "600298":"⑤品牌心智","603288":"⑤品牌心智","002027":"⑤品牌心智",
    "600690":"⑤品牌心智",
    "002508":"⑥小众冠军","002884":"⑥小众冠军",
    "002318":"⑥小众冠军","603855":"⑥小众冠军","603508":"⑥小众冠军",
    "300628":"⑥小众冠军","000708":"⑥小众冠军","000157":"⑥小众冠军",
    "600031":"⑥小众冠军","600761":"⑥小众冠军","600066":"⑥小众冠军",
    "600486":"⑥小众冠军",
    "688187":"科技⚠","300832":"科技⚠","002837":"科技⚠",
    "300627":"科技⚠","002410":"科技⚠","600845":"科技⚠",
    "002747":"科技⚠","600161":"科技⚠",
}


def batch_quote(codes):
    """腾讯批量 → {code: {price, pe, pb}}"""
    result = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i+30]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            text = r.text
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 48:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    pe = float(parts[39]) if parts[39] and parts[39] != "-" else None
                    pb = float(parts[46]) if parts[46] and parts[46] != "-" else None
                    if price and price > 0:
                        result[c] = {"price": price, "pe": pe, "pb": pb}
                except:
                    pass
        except:
            pass
    return result


def pct_rank(values, reverse=False):
    """返回分位数 0~100"""
    sorted_vals = sorted(v for v in values if v is not None)
    if not sorted_vals:
        return {}
    n = len(sorted_vals)
    result = {}
    for i, v in enumerate(sorted_vals):
        rank = round(i / (n - 1) * 100, 1) if n > 1 else 50
        if reverse:
            rank = 100 - rank
        result[v] = rank
    return result


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
    print(f"[START] 估值分位数 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    codes = [c for c in trigger if isinstance(trigger.get(c), dict)]
    data = batch_quote(codes)
    print(f"  获取 {len(data)}/{len(codes)} 只")

    # 过滤有效 PE/PB
    rows = []
    for code in codes:
        t = trigger[code]
        name = t.get("name", code)
        d = data.get(code)
        if not d:
            continue
        a = ATTR.get(code, "?")
        rows.append({
            "name": name, "code": code, "attr": a,
            "price": d["price"], "pe": d["pe"], "pb": d["pb"],
        })

    pe_vals = [r["pe"] for r in rows if r["pe"] is not None and r["pe"] > 0]
    pb_vals = [r["pb"] for r in rows if r["pb"] is not None and r["pb"] > 0]

    pe_rank = pct_rank(pe_vals)
    pb_rank = pct_rank(pb_vals)

    for r in rows:
        r["pe_pct"] = pe_rank.get(r["pe"], None)
        r["pb_pct"] = pb_rank.get(r["pb"], None)

    # PE 最便宜 TOP10
    pe_sorted = sorted([r for r in rows if r["pe"] is not None and r["pe"] > 0], key=lambda x: x["pe"])
    pb_sorted = sorted([r for r in rows if r["pb"] is not None and r["pb"] > 0], key=lambda x: x["pb"])

    # PE 最贵 TOP5
    pe_expensive = sorted([r for r in rows if r["pe"] is not None and r["pe"] > 0], key=lambda x: -x["pe"])

    lines = [
        f"估值分位数 {now:%m}.{now:%d}",
        f"框架股 PE/PB 排名 | {len(rows)}只有效数据",
    ]

    lines.append("")
    lines.append("PE 最便宜 TOP10")
    for i, r in enumerate(pe_sorted[:10]):
        lines.append(f"  {i+1}. {r['name']} PE{r['pe']:.1f}（{r['pe_pct']:.0f}%分位）{r['attr']}")

    lines.append("")
    lines.append("PE 最贵 TOP5")
    for i, r in enumerate(pe_expensive[:5]):
        lines.append(f"  {i+1}. {r['name']} PE{r['pe']:.1f}（{r['pe_pct']:.0f}%分位）{r['attr']}")

    lines.append("")
    lines.append("PB 最便宜 TOP5")
    for i, r in enumerate(pb_sorted[:5]):
        lines.append(f"  {i+1}. {r['name']} PB{r['pb']:.2f}（{r['pb_pct']:.0f}%分位）{r['attr']}")

    # 双低：PE+PB 都在前 30%
    dual_low = [r for r in rows if r["pe_pct"] is not None and r["pb_pct"] is not None
                and r["pe_pct"] <= 30 and r["pb_pct"] <= 30]
    if dual_low:
        lines.append("")
        lines.append(f"PE+PB 双低（≤30%分位）{len(dual_low)}只")
        for r in dual_low:
            lines.append(f"  - {r['name']} PE{r['pe']:.1f} PB{r['pb']:.2f} {r['attr']}")

    lines.append("")
    lines.append(f"> 分位越低越便宜 | 腾讯 parts[39]=PE [46]=PB")

    push(f"估值分位数 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
