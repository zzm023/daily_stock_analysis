#!/usr/bin/env python3
"""
估值共振检查 v1
读 framework_state.json 中的 PE/PB锚 + 触发价 → 拉实时估值 → 标记共振
搭配触发价监控使用，每日 15:00 后跑
"""
import os
import re
import json
import requests
import subprocess
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_valuation(code):
    """拉新浪 PE/PB/股息率"""
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        m = re.search(r'="(.+?)"', r.text)
        if m:
            fields = m.group(1).split(",")
            price = float(fields[3]) if fields[3] else 0
            pe = float(fields[39]) if len(fields)>39 and fields[39] else 0
            pb = float(fields[42]) if len(fields)>42 and fields[42] else 0
            return {"price": price, "pe": pe, "pb": pb}
    except:
        pass
    return {"price": 0, "pe": 0, "pb": 0}


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


def git_commit_state():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", "framework_state.json"], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "[auto] 更新估值共振状态"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("[GIT] framework_state.json 已提交")
    except Exception as e:
        print(f"[GIT] 提交失败: {e}")


def main():
    now = datetime.now()
    print(f"[START] 估值共振检查 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    resonance_hits = []

    for code, v in trigger.items():
        status = v.get("status", "")
        if status not in ("已触发", "接近"):
            continue

        pe_upper = v.get("pe_upper")
        pb_lower = v.get("pb_lower")
        if not pe_upper and not pb_lower:
            continue

        val = get_valuation(code)
        if val["price"] == 0:
            continue

        pe_ok = pb_ok = div_ok = False
        score = 0

        if pe_upper and val["pe"] > 0 and val["pe"] <= pe_upper:
            pe_ok = True
            score += 1

        if pb_lower and val["pb"] > 0 and val["pb"] <= pb_lower:
            pb_ok = True
            score += 1

        # 股息率共振
        dps = v.get("dps", 0)
        anchor = v.get("anchor_pct", 0)
        if dps and anchor and val["price"] > 0:
            yld = dps / val["price"] * 100
            if yld >= anchor:
                div_ok = True
                score += 1

        if score >= 2:
            resonance = "🟢 三振" if score == 3 else ("🟢 双振" if score == 2 else "单信号")
        else:
            resonance = "🟡 仅价格"

        trigger[code]["pe_now"] = round(val["pe"], 1)
        trigger[code]["pb_now"] = round(val["pb"], 2)
        trigger[code]["resonance"] = resonance
        trigger[code]["resonance_score"] = score
        trigger[code]["pe_ok"] = pe_ok
        trigger[code]["pb_ok"] = pb_ok
        trigger[code]["div_ok"] = div_ok

        if status == "已触发" and resonance != "🟡 仅价格":
            resonance_hits.append((v["name"], code, val["price"], resonance, score,
                                   val["pe"], pe_upper, val["pb"], pb_lower))

        print(f"  {v['name']}: PE{val['pe']:.1f}(≤{pe_upper}) PB{val['pb']:.2f}(≤{pb_lower}) → {resonance}")

    state["trigger"] = trigger
    save_state = lambda s: (s.update({"meta": {**s.get("meta", {}), "updated": now.strftime("%Y-%m-%dT%H:%M:%S")}}) or
                            open(STATE_FILE, "w", encoding="utf-8").write(json.dumps(s, ensure_ascii=False, indent=2)))
    
    # save state properly
    state["meta"] = state.get("meta", {})
    state["meta"]["updated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    if resonance_hits:
        lines = [f"## 🔬 估值共振 — {now:%Y.%m.%d}", "",
                 f"> {now:%H:%M} | 共振{len(resonance_hits)}只", ""]
        for name, code, price, res, sc, pe, peu, pb, pbl in resonance_hits:
            lines.append(f"**{name}** {res} 得分{sc}/3")
            lines.append(f"> 现价{price:.2f} PE{pe:.1f}(≤{peu}) PB{pb:.2f}(≤{pbl})")
            lines.append("")
        push(f"🔬 估值共振 {len(resonance_hits)}只 {now:%Y.%m.%d}", "\n".join(lines))

    git_commit_state()
    print(f"[DONE] {len(resonance_hits)}只共振")


if __name__ == "__main__":
    main()
