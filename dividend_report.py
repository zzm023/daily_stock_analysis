#!/usr/bin/env python3
"""
股息率周报：52只框架股票股息率 vs 防守锚
数据源：akshare stock_a_indicator_lg（东方财富，含股息率）
推送：PushPlus ｜ 每周五 20:00
"""
import akshare as ak
import os
import time
from datetime import datetime

# ============ 52只（与weekly_review同步） ============
STOCKS = [
    {"code": "600036", "name": "招商银行", "attr": "①永续债", "anchor": 4.0},
    {"code": "601601", "name": "中国太保", "attr": "①永续债", "anchor": 4.0},
    {"code": "600018", "name": "上港集团", "attr": "①永续债", "anchor": 4.0},
    {"code": "601816", "name": "京沪高铁", "attr": "①永续债", "anchor": 4.0},
    {"code": "600900", "name": "长江电力", "attr": "①永续债", "anchor": 4.0},
    {"code": "600941", "name": "中国移动", "attr": "①永续债", "anchor": 4.0},
    {"code": "600406", "name": "国电南瑞", "attr": "①永续债", "anchor": 3.0},
    {"code": "600598", "name": "北大荒",   "attr": "①永续债", "anchor": 3.0},
    {"code": "603568", "name": "伟明环保", "attr": "①候补", "anchor": 3.0},
    {"code": "600007", "name": "中国国贸", "attr": "①候补", "anchor": 4.0},
    {"code": "000429", "name": "粤高速A",  "attr": "①观察", "anchor": 4.0},
    {"code": "000895", "name": "双汇发展", "attr": "②高息成长", "anchor": 4.0},
    {"code": "000848", "name": "承德露露", "attr": "②高息成长", "anchor": 4.0},
    {"code": "000157", "name": "中联重科", "attr": "③周期拐点", "anchor": 0},
    {"code": "600585", "name": "海螺水泥", "attr": "③周期拐点", "anchor": 0},
    {"code": "000792", "name": "盐湖股份", "attr": "③周期拐点", "anchor": 0},
    {"code": "600188", "name": "兖矿能源", "attr": "③周期拐点", "anchor": 0},
    {"code": "002601", "name": "龙佰集团", "attr": "③候补", "anchor": 0},
    {"code": "600299", "name": "安迪苏",   "attr": "③候补", "anchor": 0},
    {"code": "300498", "name": "温氏股份", "attr": "③观察", "anchor": 0},
    {"code": "000651", "name": "格力电器", "attr": "④全球寡头", "anchor": 0},
    {"code": "600066", "name": "宇通客车", "attr": "④全球寡头", "anchor": 0},
    {"code": "000333", "name": "美的集团", "attr": "④全球寡头", "anchor": 0},
    {"code": "600690", "name": "海尔智家", "attr": "④全球寡头", "anchor": 0},
    {"code": "600031", "name": "三一重工", "attr": "④全球寡头", "anchor": 0},
    {"code": "600309", "name": "万华化学", "attr": "④全球寡头", "anchor": 0},
    {"code": "600660", "name": "福耀玻璃", "attr": "④全球寡头", "anchor": 0},
    {"code": "600761", "name": "安徽合力", "attr": "④全球寡头", "anchor": 0},
    {"code": "600486", "name": "扬农化工", "attr": "④全球寡头", "anchor": 0},
    {"code": "601058", "name": "赛轮轮胎", "attr": "④全球寡头", "anchor": 0},
    {"code": "603806", "name": "福斯特",   "attr": "④全球寡头", "anchor": 0},
    {"code": "000708", "name": "中信特钢", "attr": "④候补", "anchor": 0},
    {"code": "002027", "name": "分众传媒", "attr": "⑤品牌心智", "anchor": 0},
    {"code": "000538", "name": "云南白药", "attr": "⑤品牌心智", "anchor": 0},
    {"code": "603605", "name": "珀莱雅",   "attr": "⑤品牌心智", "anchor": 0},
    {"code": "605098", "name": "行动教育", "attr": "⑤品牌心智", "anchor": 0},
    {"code": "600298", "name": "安琪酵母", "attr": "⑤品牌心智", "anchor": 0},
    {"code": "300628", "name": "亿联网络", "attr": "⑤品牌心智", "anchor": 0},
    {"code": "002508", "name": "老板电器", "attr": "⑤品牌心智", "anchor": 0},
    {"code": "002032", "name": "苏泊尔",   "attr": "⑤候补", "anchor": 0},
    {"code": "002884", "name": "凌霄泵业", "attr": "⑥小众冠军", "anchor": 0},
    {"code": "002318", "name": "久立特材", "attr": "⑥小众冠军", "anchor": 0},
    {"code": "603855", "name": "华荣股份", "attr": "⑥小众冠军", "anchor": 0},
    {"code": "603288", "name": "海天味业", "attr": "⑥小众冠军", "anchor": 0},
    {"code": "603508", "name": "思维列控", "attr": "⑥小众冠军", "anchor": 0},
    {"code": "600161", "name": "天坛生物", "attr": "⑥候补", "anchor": 0},
    {"code": "300832", "name": "新产业",   "attr": "科技✅⚠", "anchor": 0},
    {"code": "688187", "name": "时代电气", "attr": "科技✅⚠", "anchor": 0},
    {"code": "300124", "name": "汇川技术", "attr": "科技观察", "anchor": 0},
    {"code": "002837", "name": "英维克",   "attr": "科技观察", "anchor": 0},
    {"code": "300627", "name": "华测导航", "attr": "科技观察", "anchor": 0},
    {"code": "002410", "name": "广联达",   "attr": "科技观察", "anchor": 0},
]


def get_dividend(code):
    """获取股息率（TTM），失败重试"""
    for attempt in range(3):
        try:
            df = ak.stock_a_indicator_lg(symbol=code)
            if df is not None and not df.empty:
                last = df.iloc[-1]
                dv = float(last.get("dv_ratio", 0) or 0)   # 股息率
                dv_ttm = float(last.get("dv_ttm", 0) or 0) # 股息率TTM
                return dv_ttm if dv_ttm else dv
        except Exception as e:
            if attempt == 2:
                print(f"  {code} 失败: {e}")
            else:
                time.sleep(5 * (attempt + 1))
    return 0


def push(title, content):
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] 无PUSHPLUS_TOKEN"); return
    import requests
    payload = {"token": token, "title": title, "content": content, "template": "markdown"}
    if topic: payload["topic"] = topic
    r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")


def main():
    print(f"[START] 股息率周报 {datetime.now()}")
    now = datetime.now()
    lines = [f"## 💰 股息率周报 — {now.strftime('%Y.%m.%d')}", "", f"> 股息率(TTM) vs 防守锚 ｜ {now.strftime('%m-%d %H:%M')}", ""]
    alarm = []
    rows = []

    for i, s in enumerate(STOCKS):
        dv = get_dividend(s["code"])
        rows.append((s, dv))
        print(f"  {i+1}/52 {s['name']}: {dv:.2f}%")
        if s["anchor"] and dv < s["anchor"]:
            alarm.append((s, dv))
        time.sleep(0.3)

    lines.append("### 🚨 跌破防守锚")
    if alarm:
        for s, dv in alarm:
            lines.append(f"- **{s['name']}** 股息率 {dv:.2f}% < 锚 {s['anchor']}%")
    else:
        lines.append("- 无")
    lines.append("")

    # 按股息率排序全表
    rows.sort(key=lambda x: -x[1])
    lines.append("### 全部52只（按股息率降序）")
    lines.append("")
    lines.append("| 股票 | 股息率TTM | 防守锚 | 状态 |")
    lines.append("|------|---------|--------|------|")
    for s, dv in rows:
        if s["anchor"]:
            if dv < s["anchor"]:
                st = "🔴 破锚"
            else:
                st = "✅ 达标"
            lines.append(f"| {s['name']} | {dv:.2f}% | {s['anchor']}% | {st} |")
        else:
            lines.append(f"| {s['name']} | {dv:.2f}% | - | - |")

    push(f"💰 股息率周报 {now.strftime('%Y.%m.%d')}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
