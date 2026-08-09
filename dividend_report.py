#!/usr/bin/env python3
"""
股息率周报 v2
联动 framework_state.json：读触发价+DPS → 写股息事件 → 自动提交
每周一 08:00 CST
"""
import requests
import re
import os
import json
import subprocess
from datetime import datetime, timedelta, date as date_type
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger": {}, "holdings": {}}


def save_state(s):
    s["meta"] = s.get("meta", {})
    s["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def git_commit_state():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", "framework_state.json"], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "[auto] 更新股息率事件"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("[GIT] framework_state.json 已提交")
    except Exception as e:
        print(f"[GIT] 提交失败: {e}")


def fetch_price(code):
    prefix = "sh" if code.startswith("6") else "sz"
    for attempt in range(3):
        try:
            r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                             headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
            r.encoding = "gbk"
            m = re.search(r'="(.+?)"', r.text)
            if m:
                price = float(m.group(1).split(",")[3])
                if price > 0:
                    return price
        except Exception:
            if attempt < 2:
                import time; time.sleep(2)
    return 0


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("[WARN] 无TOKEN"); return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now()
    print(f"[START] 股息率周报 v2 {now:%Y-%m-%d %H:%M}")

    state = load_state()
    trigger = state.get("trigger", {})

    rows = []
    dividend_events = []

    for code, v in trigger.items():
        dps = v.get("dps", 0)
        anchor = v.get("anchor_pct", 0)
        if dps == 0 or anchor == 0:
            continue

        price = fetch_price(code)
        if price == 0:
            continue

        yld = dps / price * 100
        gap = anchor - yld
        trigger_price = round(dps / anchor * 100, 2)

        rows.append((v["name"], code, price, trigger_price, dps, yld, anchor, gap))
        print(f"  {v['name']}: DPS={dps:.3f} 价={price:.2f} 息率={yld:.2f}%")

        # 更新触发价到状态文件（用股息率反推的更精确）
        trigger[code]["trigger_price"] = trigger_price
        trigger[code]["anchor_pct"] = anchor

        # 记录股息事件
        if gap <= 0:
            dividend_events.append({
                "code": code,
                "name": v["name"],
                "price": price,
                "yld": round(yld, 2),
                "anchor": anchor,
                "trigger_price": trigger_price,
                "status": "已触发",
                "excess_pp": round(-gap, 2)
            })
        elif gap <= 0.5:
            dividend_events.append({
                "code": code,
                "name": v["name"],
                "price": price,
                "yld": round(yld, 2),
                "anchor": anchor,
                "trigger_price": trigger_price,
                "status": "接近",
                "excess_pp": round(gap, 2)
            })

    state["trigger"] = trigger
    state["dividend_events"] = dividend_events
    save_state(state)

    rows.sort(key=lambda x: -x[5])

    lines = [f"## 💰 股息率周报 — {now:%Y.%m.%d}", "",
             f"> DPS/锚定读自状态文件 ｜ 现价：新浪 ｜ {now:%m-%d %H:%M}", ""]

    for name, code, price, tp, dps, yld, anchor, gap in rows:
        status = f"🔴 已触发（超{-gap:.1f}pp）" if gap < 0 else (f"🎯 持平" if gap == 0 else f"🟢 差{gap:.1f}pp")
        lines.append(f"**{name}**")
        lines.append(f"> 现价 {price:.2f} 股息率 {yld:.2f}% 锚定 {anchor:.1f}% 触发价 {tp:.2f} | {status}")
        lines.append("")

    triggered = [(n, g, y) for n, _, _, _, _, y, _, g in rows if g <= 0]
    close = [(n, g, y) for n, _, _, _, _, y, _, g in rows if 0 < g <= 0.5]
    if triggered:
        lines.append("### 🔴 已触发")
        for n, g, y in triggered:
            lines.append(f"- {n}：{y:.2f}%（超额{-g:.1f}pp）")
    if close:
        lines.append("### 🟡 接近触发")
        for n, g, y in close:
            lines.append(f"- {n}：{y:.2f}%，差{g:.1f}pp")

    lines.append("")
    lines.append(f"---")
    lines.append(f"{now:%Y-%m-%d %H:%M} | 联动状态文件")

    push(f"💰 股息率周报 {now:%Y.%m.%d}", "\n".join(lines))

    git_commit_state()
    print(f"[DONE] {len(rows)} 只")


if __name__ == "__main__":
    main()
