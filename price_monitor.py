"""
触发价监控脚本
用途：扫描52只框架股票，价格触及买入线 → PushPlus 推送
用法：python price_monitor.py
环境变量：PUSHPLUS_TOKEN（必填）、PUSHPLUS_TOPIC（可选）
"""

import os
import json
import sys
from datetime import datetime

# ========== 52只框架股票触发价（来源：framework_stocks.md） ==========
STOCKS = [
    # 优先1
    {"code": "000651", "name": "格力电器",   "trigger": 38.00, "attr": "④全球寡头"},
    {"code": "000157", "name": "中联重科",   "trigger": 7.00,  "attr": "③周期拐点"},
    {"code": "600036", "name": "招商银行",   "trigger": 35.00, "attr": "①永续债"},
    {"code": "601601", "name": "中国太保",   "trigger": 30.00, "attr": "①永续债"},
    {"code": "000895", "name": "双汇发展",   "trigger": 22.00, "attr": "②高息成长"},
    {"code": "600018", "name": "上港集团",   "trigger": 4.80,  "attr": "①永续债"},
    {"code": "601816", "name": "京沪高铁",   "trigger": 4.80,  "attr": "①永续债"},
    {"code": "600900", "name": "长江电力",   "trigger": None,  "attr": "①永续债", "note": "息率≥4%"},
    {"code": "600941", "name": "中国移动",   "trigger": 90.00, "attr": "①永续债"},
    {"code": "002027", "name": "分众传媒",   "trigger": 5.26,  "attr": "⑤品牌心智"},
    {"code": "600066", "name": "宇通客车",   "trigger": 27.00, "attr": "④全球寡头"},
    {"code": "000538", "name": "云南白药",   "trigger": 47.00, "attr": "⑤品牌心智"},
    {"code": "300832", "name": "新产业",     "trigger": 40.00, "attr": "科技绿"},
    {"code": "688187", "name": "时代电气",   "trigger": 46.00, "attr": "科技绿"},
    {"code": "603605", "name": "珀莱雅",     "trigger": 55.00, "attr": "⑤品牌心智"},
    {"code": "605098", "name": "行动教育",   "trigger": 48.00, "attr": "⑤品牌心智"},
    {"code": "603568", "name": "伟明环保",   "trigger": 14.50, "attr": "①永续债候补"},
    {"code": "000708", "name": "中信特钢",   "trigger": 13.50, "attr": "④全球寡头候补"},
    {"code": "002884", "name": "凌霄泵业",   "trigger": 15.00, "attr": "⑥小众冠军"},
    {"code": "600007", "name": "中国国贸",   "trigger": 17.50, "attr": "①永续债候补"},
    # 优先2
    {"code": "000333", "name": "美的集团",   "trigger": 68.00, "attr": "④全球寡头"},
    {"code": "600690", "name": "海尔智家",   "trigger": 20.00, "attr": "④全球寡头"},
    {"code": "600031", "name": "三一重工",   "trigger": 17.00, "attr": "④全球寡头"},
    {"code": "600309", "name": "万华化学",   "trigger": 68.00, "attr": "④全球寡头"},
    {"code": "600585", "name": "海螺水泥",   "trigger": None,  "attr": "③周期拐点", "note": "PB≤0.55"},
    {"code": "000792", "name": "盐湖股份",   "trigger": 25.00, "attr": "③周期拐点"},
    {"code": "603288", "name": "海天味业",   "trigger": 30.00, "attr": "⑥小众冠军"},
    {"code": "600298", "name": "安琪酵母",   "trigger": 35.00, "attr": "⑤品牌心智"},
    {"code": "000429", "name": "粤高速A",    "trigger": 10.50, "attr": "①永续债观察"},
    {"code": "600406", "name": "国电南瑞",   "trigger": 20.00, "attr": "①永续债"},
    {"code": "600660", "name": "福耀玻璃",   "trigger": 50.00, "attr": "④全球寡头"},
    {"code": "300628", "name": "亿联网络",   "trigger": 33.00, "attr": "⑤品牌心智"},
    {"code": "600161", "name": "天坛生物",   "trigger": 11.50, "attr": "⑥小众冠军候补"},
    {"code": "600598", "name": "北大荒",     "trigger": 11.50, "attr": "①永续债"},
    {"code": "002318", "name": "久立特材",   "trigger": 17.50, "attr": "⑥小众冠军"},
    {"code": "603855", "name": "华荣股份",   "trigger": 15.20, "attr": "⑥小众冠军"},
    # 优先3
    {"code": "002032", "name": "苏泊尔",     "trigger": 40.00, "attr": "⑤品牌心智候补"},
    {"code": "002508", "name": "老板电器",   "trigger": 14.05, "attr": "⑤品牌心智"},
    {"code": "600761", "name": "安徽合力",   "trigger": 16.50, "attr": "④全球寡头"},
    {"code": "600486", "name": "扬农化工",   "trigger": 52.00, "attr": "④全球寡头"},
    {"code": "600188", "name": "兖矿能源",   "trigger": 15.50, "attr": "③周期拐点"},
    {"code": "000848", "name": "承德露露",   "trigger": 8.00,  "attr": "②高息成长"},
    {"code": "601058", "name": "赛轮轮胎",   "trigger": 12.00, "attr": "④全球寡头"},
    {"code": "603508", "name": "思维列控",   "trigger": 21.60, "attr": "⑥小众冠军"},
    # 优先4-5
    {"code": "002601", "name": "龙佰集团",   "trigger": 13.50, "attr": "③周期拐点候补"},
    {"code": "603806", "name": "福斯特",     "trigger": 13.50, "attr": "④全球寡头"},
    {"code": "600299", "name": "安迪苏",     "trigger": 7.60,  "attr": "③周期拐点候补"},
    # 观察/X
    {"code": "300124", "name": "汇川技术",   "trigger": 47.00, "attr": "科技观察"},
    {"code": "002837", "name": "英维克",     "trigger": 43.00, "attr": "科技观察"},
    {"code": "300627", "name": "华测导航",   "trigger": 26.50, "attr": "科技观察"},
    {"code": "002410", "name": "广联达",     "trigger": 8.50,  "attr": "科技观察"},
    {"code": "300498", "name": "温氏股份",   "trigger": None,  "attr": "③周期观察", "note": "待定"},
]

# ========== 价格获取 ==========

def get_price_akshare(code: str) -> float | None:
    """通过 akshare 获取实时/收盘价"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if row.empty:
            return None
        return float(row.iloc[0]["最新价"])
    except Exception as e:
        print(f"  ⚠ akshare 获取 {code} 失败: {e}")
        return None


def get_price_tencent(code: str) -> float | None:
    """腾讯行情接口兜底"""
    try:
        import requests
        if code.startswith("6"):
            full = f"sh{code}"
        else:
            full = f"sz{code}"
        url = f"http://qt.gtimg.cn/q={full}"
        resp = requests.get(url, timeout=5)
        resp.encoding = "gbk"
        text = resp.text
        if "~" not in text:
            return None
        parts = text.split("~")
        if len(parts) < 4:
            return None
        return float(parts[3])
    except Exception:
        return None


def get_price(code: str) -> float | None:
    """获取最新价，优先 akshare，兜底腾讯"""
    price = get_price_akshare(code)
    if price is None:
        price = get_price_tencent(code)
    return price


# ========== PushPlus 推送 ==========

def pushplus_send(title: str, content: str):
    token = os.environ.get("PUSHPLUS_TOKEN", "")
    topic = os.environ.get("PUSHPLUS_TOPIC", "")
    if not token:
        print("❌ PUSHPLUS_TOKEN 未配置，跳过推送")
        return

    try:
        import requests
        url = "http://www.pushplus.plus/send"
        data = {
            "token": token,
            "title": title,
            "content": content,
            "template": "markdown",
        }
        if topic:
            data["topic"] = topic
        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()
        if result.get("code") == 200:
            print("✅ PushPlus 推送成功")
        else:
            print(f"⚠ PushPlus 返回: {result}")
    except Exception as e:
        print(f"❌ PushPlus 推送失败: {e}")


# ========== 主逻辑 ==========

def main():
    print(f"========== 触发价监控 | {datetime.now():%Y-%m-%d %H:%M:%S} ==========\n")

    results = {"hit": [], "close": [], "normal": 0, "failed": 0, "no_trigger": 0}

    for s in STOCKS:
        code = s["code"]
        name = s["name"]
        trigger = s["trigger"]

        if trigger is None:
            results["no_trigger"] += 1
            continue

        price = get_price(code)

        if price is None:
            print(f"❌ {name}({code}) 获取价格失败")
            results["failed"] += 1
            continue

        gap_pct = (price - trigger) / trigger * 100

        if price <= trigger:
            status = "🔥 已触发"
            results["hit"].append({**s, "price": price, "gap": gap_pct})
        elif gap_pct <= 10:
            status = "⏳ 即将"
            results["close"].append({**s, "price": price, "gap": gap_pct})
        else:
            status = "   "
            results["normal"] += 1

        print(f"{status} | {name:6s}({code}) | 现价{price:>8.2f} | 触发{trigger:>8.2f} | 差距{gap_pct:>+5.1f}% | {s['attr']}")

    print(f"\n========== 汇总 ==========")
    print(f"🔥 已触发: {len(results['hit'])} 只")
    print(f"⏳ 即将（≤10%）: {len(results['close'])} 只")
    print(f"   正常: {results['normal']} 只")
    print(f"   无触发价: {results['no_trigger']} 只")
    print(f"   获取失败: {results['failed']} 只")

    # ===== 构建推送内容 =====
    if not results["hit"] and not results["close"]:
        print("\n📭 无触发/即将触发股票，不推送")
        return

    lines = [
        f"## 📊 触发价监控日报",
        f"**{datetime.now():%Y-%m-%d %H:%M}**",
        "",
    ]

    if results["hit"]:
        lines.append("### 🔥 已触发（现价 ≤ 触发价）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 | 属性 |")
        lines.append("|------|------|--------|------|------|")
        for s in results["hit"]:
            lines.append(f"| {s['name']}({s['code']}) | {s['price']:.2f} | {s['trigger']:.2f} | {s['gap']:+.1f}% | {s['attr']} |")
        lines.append("")

    if results["close"]:
        lines.append("### ⏳ 即将触发（距触发 ≤10%）")
        lines.append("")
        lines.append("| 股票 | 现价 | 触发价 | 差距 | 属性 |")
        lines.append("|------|------|--------|------|------|")
        for s in results["close"]:
            lines.append(f"| {s['name']}({s['code']}) | {s['price']:.2f} | {s['trigger']:.2f} | {s['gap']:+.1f}% | {s['attr']} |")
        lines.append("")

    lines.append("> ⚠️ 触发 ≠ 立即买，需综合判断。参考框架交易纪律：左侧分层，目标价打9折，仓位减半，观察1周。")

    content = "\n".join(lines)
    pushplus_send("📊 触发价监控日报", content)


if __name__ == "__main__":
    main()
