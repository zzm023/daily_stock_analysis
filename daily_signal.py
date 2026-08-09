"""
每日信号汇总 v2：触发快照 + 持仓快照 + 事件汇总 → DeepSeek → 推送
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


def get_price(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        resp = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=5)
        resp.encoding = "gbk"
        parts = resp.text.split("~")
        if len(parts) >= 4:
            return float(parts[3])
    except:
        pass
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if not row.empty:
            return float(row.iloc[0]["最新价"])
    except:
        pass
    return 0


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
    now = datetime.now()
    lines = [f"分析以下投资框架数据，给出操作建议。\n"]

    # ── 持仓快照 ──
    hold = state.get("holdings", {})
    cash = hold.get("cash", 0)
    holdings_list = []
    for k, v in hold.items():
        if k == "cash" or not isinstance(v, dict):
            continue
        price = get_price(k)
        if price == 0:
            price = v.get("cost", 0)
        pnl = (price - v["cost"]) / v["cost"] * 100 if v.get("cost") else 0
        holdings_list.append({
            "name": v.get("name",""), "code": k, "shares": v.get("shares",0),
            "cost": v.get("cost",0), "price": round(price,2),
            "pnl_pct": round(pnl, 2), "date": v.get("date","")
        })

    if holdings_list:
        lines.append("## 持仓")
        for h in holdings_list:
            lines.append(f"- {h['name']}({h['code']}) {h['shares']}股 成本{h['cost']} 现价{h['price']} 盈亏{h['pnl_pct']:+.1f}% 建仓{h['date']}")
        lines.append(f"\n现金: {cash:,.0f}元")
        total_value = cash + sum(h["price"] * h["shares"] for h in holdings_list)
        lines.append(f"总资产: {total_value:,.0f}元")
        lines.append("")

    # ── 触发清单 ──
    trigger = state.get("trigger", {})
    active = [(c, v) for c, v in trigger.items() if v.get("status") in ("已触发","接近")]
    if active:
        lines.append("## 触发清单")
        active.sort(key=lambda x: x[1].get("gap_pct", 99))
        for c, v in active:
            lines.append(f"- {v['name']}({c}) 现价{v.get('current_price',0):.2f} 触发价{v['trigger_price']:.2f} "
                        f"差距{v.get('gap_pct',99):+.1f}% {v['status']}")
        lines.append("")

    # ── 事件 ──
    events = state.get("events", [])
    if events:
        lines.append("## 增减持/公告")
        for e in events:
            lines.append(f"- {e.get('name','')}({e.get('code','')}) {e.get('date','')} {e.get('title','')} [{e.get('impact','')}]")
        lines.append("")

    comm = state.get("commodity_events", [])
    if comm:
        lines.append("## 商品异动")
        for c in comm:
            in_t = c.get("in_trigger", [])
            lines.append(f"- {c.get('commodity','')} {c.get('change_pct',0)*100:+.1f}% {'🔴命中' if in_t else ''}")
        lines.append("")

    div_events = state.get("dividend_events", [])
    if div_events:
        lines.append("## 股息率")
        for d in div_events:
            lines.append(f"- {d.get('name','')} 股息率{d.get('yld',0):.2f}% 锚定{d.get('anchor',0):.1f}% {d.get('status','')}")
        lines.append("")

    return "\n".join(lines)


def main():
    now = datetime.now()
    print(f"[START] 每日信号 v2 {now:%Y-%m-%d %H:%M}")

    state = load_framework_state(str(STATE_FILE))
    data_section = build_prompt(state)

    # 判断有没有内容
    trigger = state.get("trigger", {})
    has_active = any(v.get("status") in ("已触发","接近") for v in trigger.values())
    has_events = state.get("events", []) or state.get("commodity_events", []) or state.get("dividend_events", [])
    has_holdings = any(k != "cash" and isinstance(v, dict) for k, v in state.get("holdings", {}).items())

    # ── 块状推送（基础信息，LLM 不需要时也发） ──
    content = f"## 📊 每日信号 — {now:%Y.%m.%d}\n\n"

    # 持仓快照
    hold = state.get("holdings", {})
    cash = hold.get("cash", 0)
    hlist = []
    for k, v in hold.items():
        if k == "cash" or not isinstance(v, dict):
            continue
        price = get_price(k)
        if price == 0:
            price = v.get("cost", 0)
        pnl = (price - v["cost"]) / v["cost"] * 100 if v.get("cost") else 0
        hlist.append((v.get("name",""), k, v.get("shares",0), v.get("cost",0), round(price,2), round(pnl,2), v.get("date","")))

    if hlist:
        content += "### 💼 持仓\n"
        for name, code, shares, cost, price, pnl, date in hlist:
            content += f"**{name}** {shares}股 成本{cost} 现价{price} 盈亏{pnl:+.1f}%\n"
            content += f"> 建仓 {date} | 市值 {shares*price:,.0f}元\n\n"
        total_val = cash + sum(p * s for _, _, s, _, p, _, _ in hlist)
        content += f"💰 现金 {cash:,.0f} ｜ 总资产 {total_val:,.0f}\n\n"

    # 触发快照
    active = [(c, v) for c, v in trigger.items() if v.get("status") in ("已触发","接近")]
    if active:
        active.sort(key=lambda x: x[1].get("gap_pct", 99))
        hit = [(c, v) for c, v in active if v["status"] == "已触发"]
        close = [(c, v) for c, v in active if v["status"] == "接近"]
        content += f"### 🎯 触发清单 — 🔴{len(hit)}只 🟡{len(close)}只\n\n"
        if hit:
            content += "**已触发**\n"
            for c, v in hit:
                content += f"- {v['name']} 现价{v.get('current_price',0):.2f} 触发价{v['trigger_price']:.2f} 超{abs(v.get('gap_pct',0)):.1f}%\n"
            content += "\n"
        if close:
            content += "**接近(≤10%)**\n"
            for c, v in close:
                content += f"- {v['name']} 现价{v.get('current_price',0):.2f} 触发价{v['trigger_price']:.2f} 差{v.get('gap_pct',0):.1f}%\n"
            content += "\n"

    # 事件
    events = state.get("events", [])
    if events:
        content += f"### 📢 增减持 ({len(events)}条)\n"
        for e in events:
            content += f"- {e.get('name','')} {e.get('date','')} {e.get('title','')} [{e.get('impact','')}]\n"
        content += "\n"

    comm = state.get("commodity_events", [])
    if comm:
        content += "### 📦 商品异动\n"
        for c in comm:
            in_t = c.get("in_trigger", [])
            tag = " 🔴命中清单" if in_t else ""
            content += f"- {c.get('commodity','')} {c.get('change_pct',0)*100:+.1f}%{tag}\n"
        content += "\n"

    div_events = state.get("dividend_events", [])
    if div_events:
        content += "### 💰 股息率\n"
        for d in div_events:
            content += f"- {d.get('name','')} 股息率{d.get('yld',0):.2f}% 锚定{d.get('anchor',0):.1f}% {d.get('status','')}\n"
        content += "\n"

    # ── LLM 分析 ──
    if has_active or has_events:
        prompt = data_section + """
你是投资分析助手，基于以上数据，请用中文给出简洁分析：

1. 持仓评估：现有持仓是否需要操作？
2. 触发判断：已觸发的股票是否应该买入？参考框架纪律（左侧分层、目标价9折、仓位减半、观察1周）
3. 风险提示：今天最需要注意的风险
4. 操作建议：今天是否有明确的操作建议？

格式：块状分段，每段2-3行，不编造数据。"""

        print("[LLM] 调用DeepSeek...")
        analysis = call_deepseek(prompt, temperature=0.1, max_tokens=1200)
        print(f"[LLM] 返回 {len(analysis)} 字符")

        content += f"### 🤖 分析\n\n{analysis}\n\n"
    else:
        content += "### 🤖 分析\n\n今日无触发变动和新增事件，维持等待。\n\n"

    content += f"---\n{now:%H:%M} | DeepSeek API"

    push(f"📊 每日信号 {now:%Y.%m.%d}", content)

    # 清空当日事件
    state["events"] = []
    state["commodity_events"] = []
    state["dividend_events"] = []
    save_framework_state(state, str(STATE_FILE))

    print("[DONE]")


if __name__ == "__main__":
    main()
