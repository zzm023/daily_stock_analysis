"""
每日信号汇总 v3：触发+共振+事件 → DeepSeek → 推送
每日 15:30 CST（触发价监控 15:00 + 估值共振检查 16:15 之后）
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

from llm_utils import (
    call_deepseek, load_framework_state, save_framework_state, FRAMEWORK_SYSTEM
)

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
STATE_FILE = Path(__file__).parent / "framework_state.json"

ALL_STOCKS = {
    "600036":"招商银行","601601":"中国太保","600018":"上港集团","601816":"京沪高铁",
    "600900":"长江电力","600941":"中国移动","600406":"国电南瑞","600598":"北大荒",
    "603568":"伟明环保","600007":"中国国贸","000429":"粤高速A","000157":"中联重科",
    "600585":"海螺水泥","000792":"盐湖股份","600188":"兖矿能源","002601":"龙佰集团",
    "600299":"安迪苏","300498":"温氏股份","000651":"格力电器","600066":"宇通客车",
    "000333":"美的集团","600690":"海尔智家","600031":"三一重工","600309":"万华化学",
    "600660":"福耀玻璃","600761":"安徽合力","600486":"扬农化工","601058":"赛轮轮胎",
    "603806":"福斯特","000708":"中信特钢","002027":"分众传媒","000538":"云南白药",
    "603605":"珀莱雅","605098":"行动教育","600298":"安琪酵母","300628":"亿联网络",
    "002508":"老板电器","002032":"苏泊尔","002884":"凌霄泵业","002318":"久立特材",
    "603855":"华荣股份","603288":"海天味业","603508":"思维列控","600161":"天坛生物",
    "300832":"新产业","688187":"时代电气","300124":"汇川技术","002837":"英维克",
    "300627":"华测导航","002410":"广联达"
}


def pushplus_send(title, content):
    if not PUSHPLUS_TOKEN:
        print("[WARN] 无TOKEN"); return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def build_data_section(state):
    """组装今天的数据"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"## 数据快照 {today}\n"]

    # 1. 触发 — 已触发
    triggered = []
    for code, v in state.get("trigger", {}).items():
        if v.get("status") == "已触发":
            resonance = v.get("resonance", "")
            score = v.get("resonance_score", 0)
            resonance_tag = f" [{resonance}]" if resonance else ""
            triggered.append(
                f"- {v['name']}({code}) 现价{v.get('current_price',0):.2f} "
                f"触发价{v['trigger_price']:.2f} "
                f"PE{v.get('pe_now','?')} PB{v.get('pb_now','?')} "
                f"{resonance_tag}"
            )
    if triggered:
        lines.append("### 🔴 已触发\n" + "\n".join(triggered) + "\n")

    # 2. 接近 — 分双振/仅价格
    close_resonance = []
    close_price_only = []
    for code, v in state.get("trigger", {}).items():
        if v.get("status") == "接近":
            gap = v.get("gap_pct", 99)
            resonance = v.get("resonance", "")
            score = v.get("resonance_score", 0)
            entry = (
                f"- {v['name']}({code}) 现价{v.get('current_price',0):.2f} "
                f"触发价{v['trigger_price']:.2f} 距{abs(gap):.1f}% "
                f"PE{v.get('pe_now','?')} PB{v.get('pb_now','?')} "
                f"[{resonance}]"
            )
            if score >= 2:
                close_resonance.append(entry)
            else:
                close_price_only.append(entry)

    if close_resonance:
        lines.append(f"### 🟢 接近+估值共振 ({len(close_resonance)}只)\n" + "\n".join(close_resonance) + "\n")

    if close_price_only:
        lines.append(f"### 🟡 接近·仅价格 ({len(close_price_only)}只)\n" + "\n".join(close_price_only) + "\n")

    if not triggered and not close_resonance and not close_price_only:
        lines.append("### 触发清单\n无股票处于触发/接近状态。\n")

    # 3. 今日事件
    daily = state.get("events_daily", [])
    if daily:
        lines.append("### 今日事件\n")
        for e in daily:
            lines.append(f"- [{e.get('type','')}] {e.get('desc','')}")
        lines.append("")

    # 4. 大宗商品
    comm = state.get("commodity_events", [])
    if comm:
        lines.append("### 大宗商品\n")
        for c in comm:
            in_trigger = c.get("in_trigger", [])
            tag = " 🔴命中" if in_trigger else ""
            lines.append(f"- {c.get('commodity','')} {c.get('change_str','')}{tag}")
        lines.append("")

    # 5. 增减持
    insider = state.get("events", [])
    if insider:
        lines.append("### 增减持/公告\n")
        for e in insider:
            lines.append(f"- {e.get('stock','')} {e.get('date','')} {e.get('summary','')}")
        lines.append("")

    # 6. 持仓摘要
    hold = state.get("holdings", {})
    hlist = []
    total_val = hold.get("cash", 0)
    for k, v in hold.items():
        if k != "cash" and isinstance(v, dict):
            hlist.append(f"{v.get('name','')} {v.get('shares',0)}股")
    if hlist:
        lines.append("### 持仓\n" + " | ".join(hlist) + f"\n现金 {hold.get('cash',0):,.0f}\n")

    return "\n".join(lines)


def main():
    now = datetime.now()
    print(f"[START] 每日信号汇总 v3 {now:%Y-%m-%d %H:%M}")

    state = load_framework_state(str(STATE_FILE))

    has_active = any(
        v.get("status") in ("已触发", "接近")
        for v in state.get("trigger", {}).values()
    )
    has_events = (
        state.get("events_daily", []) or
        state.get("commodity_events", []) or
        state.get("events", [])
    )

    if not has_active and not has_events:
        print("[INFO] 无触发清单，无事件")
        pushplus_send(
            f"📊 每日信号 {now:%Y.%m.%d}",
            f"## 📊 每日信号 — {now:%Y.%m.%d}\n\n无触发变动，无新增事件。保持等待。\n\n---\n{now:%H:%M}"
        )
        return

    data_section = build_data_section(state)
  prompt = data_section + """

严格规则：
- 只分析上面数据中出现的股票，禁止提到任何未列出的股票名称
- 如果数据中显示"触发0只"，就说今天没有触发信号，不要编造
- 如果数据中显示"接近+共振0只"，就说当前没有
- 不确定就写"数据不足，无法判断"

请分析：
1. 已触发股票（如有）：估值共振确认情况？PE+PB+股息哪几项达标？
2. 接近+共振股票：距触发价最近的前3只是哪些？
3. 操作建议：今天是否有明确买入信号？
4. 一句话风险提示

输出格式：每条结论2-3行，用---分隔。"""
    
    print("[LLM] 调用DeepSeek分析...")
    analysis = call_deepseek(prompt, temperature=0.1, max_tokens=1500)
    print(f"[LLM] 返回 {len(analysis)} 字符")

    # 统计
    trig_count = len([v for v in state.get("trigger",{}).values() if v.get("status")=="已触发"])
    close_res = len([v for v in state.get("trigger",{}).values() 
                     if v.get("status")=="接近" and v.get("resonance_score",0)>=2])
    close_price = len([v for v in state.get("trigger",{}).values() 
                       if v.get("status")=="接近" and v.get("resonance_score",0)<2])

    content = f"## 📊 每日信号 — {now:%Y.%m.%d}\n\n"
    content += f"> 🔴已触发{trig_count}只 | 🟢接近+共振{close_res}只 | 🟡接近·仅价格{close_price}只\n\n"
    content += "### 🤖 分析结论\n\n"
    content += analysis
    content += f"\n\n---\n{now:%H:%M} | DeepSeek V4"

    pushplus_send(f"📊 每日信号 {now:%Y.%m.%d}", content)

    state["events_daily"] = []
    save_framework_state(state, str(STATE_FILE))
    print("[DONE]")


if __name__ == "__main__":
    main()
