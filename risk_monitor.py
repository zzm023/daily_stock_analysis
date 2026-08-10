"""
仓位风控 v2
每日检查：单只占比/超标告警/框架外持仓/现金占比
纯文本格式，手机友好
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 框架内股票代码 → 类别上限
FRAMEWORK_MAP = {
    "600036":("招商银行","①永续债",15), "601601":("中国太保","①永续债",15),
    "600018":("上港集团","①永续债",15), "601816":("京沪高铁","①永续债",15),
    "600900":("长江电力","①永续债",15), "600941":("中国移动","①永续债",15),
    "600406":("国电南瑞","①永续债候补",8), "600598":("北大荒","①永续债候补",8),
    "603568":("伟明环保","①永续债候补",8), "600007":("中国国贸","①永续债候补",8),
    "000429":("粤高速A","②高息成长",8),
    "600585":("海螺水泥","③周期拐点",3), "000792":("盐湖股份","③周期拐点",3),
    "600188":("兖矿能源","③周期拐点",3), "002601":("龙佰集团","③周期拐点",3),
    "600299":("安迪苏","③周期拐点",3), "300498":("温氏股份","③周期拐点",3),
    "000651":("格力电器","④全球寡头",8), "600066":("宇通客车","④全球寡头",8),
    "000333":("美的集团","④全球寡头",8), "600690":("海尔智家","④全球寡头",8),
    "600031":("三一重工","④全球寡头",8), "600309":("万华化学","④全球寡头",8),
    "600660":("福耀玻璃","④全球寡头",8), "600761":("安徽合力","④全球寡头",8),
    "600486":("扬农化工","④全球寡头",8), "601058":("赛轮轮胎","④全球寡头",8),
    "603806":("福斯特","④全球寡头",8),
    "000708":("中信特钢","④全球寡头候补",8), "000157":("中联重科","④全球寡头候补",8),
    "002027":("分众传媒","⑤品牌心智",8),
    "000538":("云南白药","⑤品牌心智",8), "603605":("珀莱雅","⑤品牌心智",8),
    "605098":("行动教育","⑤品牌心智",8), "600298":("安琪酵母","⑤品牌心智",8),
    "300628":("亿联网络","⑤品牌心智",8), "002508":("老板电器","⑤品牌心智",8),
    "002032":("苏泊尔","⑤品牌心智候补",8),
    "002884":("凌霄泵业","⑥小众冠军",8), "002318":("久立特材","⑥小众冠军",8),
    "603855":("华荣股份","⑥小众冠军",8), "603288":("海天味业","⑥小众冠军",8),
    "603508":("思维列控","⑥小众冠军",8),
    "600161":("天坛生物","⑥小众冠军候补",8),
    "300832":("新产业","科技绿",8), "688187":("时代电气","科技绿",8),
    "300124":("汇川技术","科技观察",4), "002837":("英维克","科技观察",4),
    "300627":("华测导航","科技观察",4), "002410":("广联达","科技观察",4),
}


def get_price(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) >= 4 and parts[3]:
            return float(parts[3])
    except:
        pass
    return 0


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now()
    print(f"[START] 仓位风控 v2 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    total_capital = state.get("meta", {}).get("total_capital", 400000)
    cash = hold.get("cash", 0)

    warnings = []
    positions = []

    for code, v in hold.items():
        if code == "cash" or not isinstance(v, dict):
            continue

        name = v.get("name", code)
        cost = v.get("cost", 0)
        shares = v.get("shares", 0)
        note = v.get("note", "")

        # 负成本特殊处理
        if cost < 0:
            price = get_price(code)
            market_value = price * shares if price else 0
            positions.append({
                "name": name, "cost_basis": 0, "cost_pct": 0,
                "market_value": market_value if market_value else "—",
                "limit": "—", "attr": "零成本", "over": False, "outside": False,
                "special": "🏆 负成本·永久持有"
            })
            continue

        cost_basis = cost * shares
        pct = cost_basis / total_capital * 100

        price = get_price(code)
        market_value = price * shares if price else cost_basis

        # 查框架
        if code in FRAMEWORK_MAP:
            _, attr, limit = FRAMEWORK_MAP[code]
            outside = False
        else:
            attr = "框架外"
            limit = 10
            outside = True

        is_over = pct > limit

        positions.append({
            "name": name, "cost_basis": cost_basis, "cost_pct": pct,
            "market_value": market_value, "limit": limit,
            "attr": attr, "over": is_over, "outside": outside
        })

        if is_over:
            warnings.append(f"⚠️ **{name}** 成本占比{pct:.1f}% > {attr}上限{limit}%")
        if outside and "框架外" not in note:
            warnings.append(f"📌 **{name}** 非框架内股票，注意仓位控制")

    positions.sort(key=lambda x: x["cost_pct"], reverse=True)

    # 总资产
    stock_value = sum(p["market_value"] for p in positions if isinstance(p["market_value"], (int, float)))
    total_value = stock_value + cash
    cash_pct = cash / total_value * 100 if total_value else 0

    # 推送
    lines = [f"## 🛡️ 仓位风控 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 总资产{total_value:,.0f} | 现金{cash:,.0f}（{cash_pct:.0f}%）", ""]

    for p in positions:
        if p.get("special"):
            lines.append(f"**{p['name']}** | {p['special']} | 市值{p['market_value']}")
            lines.append("")
            continue

        status = "🔴超标" if p["over"] else "🟡框架外" if p["outside"] else "🟢"
        mv_s = f"{p['market_value']:,.0f}" if isinstance(p['market_value'], (int, float)) else p['market_value']
        lines.append(
            f"**{p['name']}** | 成本占比{p['cost_pct']:.1f}% | 市值{mv_s} | "
            f"{p['attr']}上限{p['limit']}% | {status}"
        )
        lines.append("")

    if warnings:
        lines.append("### ⚠️ 风控提醒")
        for w in warnings:
            lines.append(w)
        lines.append("")
    else:
        lines.append("> ✅ 所有持仓在框架上限内，无超标。")

    lines.append("")
    lines.append(f"📊 现金占比{cash_pct:.0f}% → " +
                 ("充裕，可在触发时果断出手" if cash_pct >= 30 else
                  "偏低，新买入需谨慎" if cash_pct >= 15 else "紧张，优先等收割"))
    push(f"🛡️ 仓位风控 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] {len(warnings)}条警告")


if __name__ == "__main__":
    main()
