"""
买入清单 v1
每周筛选：距触发≤10% + 未持仓 + 行业不超标 → 推送可买清单
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
WARN = 30

SECTOR = {
    "600036":"银行","601601":"保险","000429":"交通运输","600018":"交通运输","601816":"交通运输",
    "600900":"电力","600941":"通信","600188":"煤炭","600585":"建材","603568":"环保",
    "600007":"房地产","000157":"工程机械","600031":"工程机械","600761":"工程机械","600660":"汽车",
    "601058":"汽车","600066":"汽车","002508":"家电","002032":"家电","000651":"家电","000333":"家电",
    "600690":"家电","000792":"化工","002601":"化工","600299":"化工","600309":"化工","600486":"化工",
    "603806":"化工","002027":"传媒","000538":"医药","600161":"医药","300832":"医疗器械",
    "300498":"农业","600598":"农业","000708":"钢铁","002318":"钢铁","002884":"通用设备",
    "002837":"通用设备","603855":"电力设备","600406":"电力设备","603508":"铁路设备",
    "688187":"半导体","300124":"工控自动化","002747":"工控自动化","002410":"软件","600845":"软件",
    "603605":"化妆品","605098":"教育","600298":"食品饮料","603288":"食品饮料","300628":"通信",
    "300627":"通信",
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
    print(f"[START] 买入清单 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    # 持仓代码 + 名字
    held_codes = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    held_names = {hold[c].get("name", "") for c in held_codes if isinstance(hold.get(c), dict)}

    # 行业市值
    all_codes = list(held_codes | {c for c in trigger if isinstance(trigger.get(c), dict)})
    prices = batch_prices(all_codes)

    sec_mv = {}
    for code in held_codes:
        v = hold[code]
        if not isinstance(v, dict):
            continue
        price = prices.get(code, 0)
        mv = price * v.get("shares", 0) if price else v.get("cost", 0) * v.get("shares", 0)
        sec = SECTOR.get(code, "其他")
        sec_mv[sec] = sec_mv.get(sec, 0) + mv
    total_mv = sum(sec_mv.values())

    candidates = []
    for code, t in trigger.items():
        if not isinstance(t, dict):
            continue
        if code in held_codes:
            continue
        name = t.get("name", code)
        target = t.get("trigger_price", 0)
        resonance = t.get("resonance", "")
        pe_now = t.get("pe_now", 0)
        pb_now = t.get("pb_now", 0)
        price = prices.get(code, 0)
        if not price or not target:
            continue

        gap = round((price - target) / target * 100, 1)
        if gap > 10 or gap < -5:
            continue

        # 行业检查
        sec = SECTOR.get(code, "其他")
        sec_pct = sec_mv.get(sec, 0) / total_mv * 100 if total_mv else 0
        if sec_pct > WARN:
            continue

        candidates.append({
            "name": name, "code": code, "price": price, "target": target,
            "gap": gap, "pe": pe_now, "pb": pb_now,
            "resonance": "双振" if "双振" in resonance else "",
            "sec": sec, "sec_pct": sec_pct,
        })

    candidates.sort(key=lambda x: x["gap"])

    lines = [f"# 买入清单 {now:%m}.{now:%d}",
             f"距触发≤10% 未持仓 行业≤{WARN}% 共{len(candidates)}只", ""]

    if not candidates:
        lines.append("无符合条件的标的。等。")
    else:
        for c in candidates:
            r_tag = "⚡双振" if c["resonance"] else ""
            lines.append(
                f"- **{c['name']}** 现{c['price']:.2f} 触发{c['target']:.2f} "
                f"距{c['gap']:+.1f}% PE{c['pe']:.1f} PB{c['pb']:.2f} "
                f"{r_tag} {c['sec']}{c['sec_pct']:.0f}%"
            )
    lines.append("")
    lines.append(f"> 每周一推送 仅供清单参考 非买入建议")

    push(f"买入清单 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] {len(candidates)}只")


if __name__ == "__main__":
    main()
