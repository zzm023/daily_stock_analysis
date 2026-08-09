"""
每日信号汇总：聚合触发价/增减持/大宗商品/公告
调DeepSeek LLM分析 → PushPlus推送结论
每日 15:30 CST
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

from llm_utils import call_deepseek, load_framework_state, save_framework_state

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
STATE_FILE = Path(__file__).parent / "framework_state.json"

ALL_STOCKS = {
    "600036":"招商银行","601601":"中国太保","600018":"上港集团","601816":"京沪高铁",
    "600900":"长江电力","600941":"中国移动","600406":"国电南瑞","600598":"北大荒",
    "603568":"伟明环保","600007":"中国国贸","000429":"粤高速A","002027":"分众传媒",
}

STOCK_NAMES = {
    "000792":"盐湖股份","600309":"万华化学","002601":"龙佰集团",
    "600299":"安迪苏","600585":"海螺水泥","600188":"兖矿能源",
    "603806":"福斯特","601058":"赛轮轮胎",
}


def push(title, content):
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


def build_prompt(state):
    """组装数据供LLM分析"""
    now = datetime.now()
    lines = [f"## 数据快照 {now:%Y-%m-%d}\n"]

    # 触发清单
    trigger = state.get("trigger", {})
    active = [(c, v) for c, v in trigger.items() if v.get("status") in ("已触发","接近")]
    if active:
        lines.append("### 触发清单\n")
        for c, v in active:
            lines.append(f"- {v['name']}({c}) 现价{v.get('current_price',0):.2f} 触发价{v['trigger_price']:.2f} 状态:{v['status']}")
        lines.append("")
    else:
        lines.append("### 触发清单\n无股票处于触发/接近状态。\n")

    # 增减持
    events = state.get("events", [])
    if events:
        lines.append("### 增减持/公告\n")
        for e in events:
            lines.append(f"- {e.get('name','')}({e.get('code','')}) {e.get('date','')} {e.get('title','')} | {e.get('impact','')}")
        lines.append("")

    # 大宗商品
    comm = state.get("commodity_events", [])
    if comm:
        lines.append("### 大宗商品异动\n")
        for c in comm:
            in_t = c.get("in_trigger", [])
            trigger_names = [f"{STOCK_NAMES.get(x,x)}({x})" for x in in_t]
            tag = "🔴命中触发清单" if in_t else "⚪不在清单"
            lines.append(f"- {c.get('commodity','')} {c.get('change_pct',0)*100:+.1f}% {tag} {', '.join(trigger_names)}")
        lines.append("")

    # 持仓
    hold = state.get("holdings", {})
    hlist = []
    for k, v in hold.items():
        if k != "cash" and isinstance(v, dict):
            hlist.append(f"{v.get('name','')} {v.get('shares',0)}股 成本{v.get('cost',0)}")
    if hlist:
        lines.append("### 持仓\n" + "\n".join(hlist) + f"\n现金 {hold.get('cash',0):,.0f}\n")

    return "\n".join(lines)


def main():
    now = datetime.now()
    print(f"[START] 每日信号汇总 {now:%Y-%m-%d %H:%M}")

    state = load_framework_state(str(STATE_FILE))

    # 判断有没有值得分析的内容
    trigger = state.get("trigger", {})
    has_active = any(v.get("status") in ("已触发","接近") for v in trigger.values())
    has_events = state.get("events", []) or state.get("commodity_events", [])

    data_section = build_prompt(state)

    if not has_active and not has_events:
        print("[INFO] 无触发清单，无事件")
        push(
            f"📊 每日信号 {now:%Y.%m.%d}",
            f"## 📊 每日信号 — {now:%Y.%m.%d}\n\n无触发清单变动，无新增事件。\n\n{data_section}\n\n---\n{now:%H:%M}"
        )
        return

    # 调LLM
    prompt = data_section + """
请分析：
1. 哪些股票到达击球点？
2. 今日事件对触发价有影响吗？
3. 需要调整条件单的建议
4. 风险提示

格式：块状，每条一行结论，不编造数据。"""
    
    print("[LLM] 调用DeepSeek...")
    analysis = call_deepseek(prompt, temperature=0.1, max_tokens=1500)
    print(f"[LLM] 返回 {len(analysis)} 字符")

    content = f"## 📊 每日信号 — {now:%Y.%m.%d}\n\n"
    content += f"> 触发{len([v for v in trigger.values() if v.get('status') in ('已触发','接近')])}只 | 事件{len(state.get('events',[]))}条\n\n"
    content += "### 🤖 分析结论\n\n"
    content += analysis
    content += f"\n\n---\n{now:%H:%M} | DeepSeek V3"

    push(f"📊 每日信号 {now:%Y.%m.%d}", content)

    # 清空当日事件
    state["events"] = []
    state["commodity_events"] = []
    save_framework_state(state, str(STATE_FILE))

    print("[DONE]")


if __name__ == "__main__":
    main()
