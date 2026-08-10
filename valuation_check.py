#!/usr/bin/env python3
"""
估值共振检查 v3
数据源：东方财富push2 API（直连，不需akshare）
每日 16:15 CST
"""
import os
import json
import requests
import subprocess
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_valuation_batch(codes):
    """东方财富 push2 API 批量获取 PE/PB/现价"""
    results = {}
    batch_size = 20
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        secids = []
        for c in batch:
            mkt = "1" if c.startswith("6") else "0"
            secids.append(f"{mkt}.{c}")
        url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f9,f23&secids={','.join(secids)}"
        try:
            r = requests.get(url, timeout=15, headers={"Referer": "https://quote.eastmoney.com"})
            d = r.json()
            if d.get("data") and d["data"].get("diff"):
                for item in d["data"]["diff"]:
                    code = item.get("f12", "")
                    try:
                        results[code] = {
                            "price": item.get("f2", 0) or 0,
                            "pe": item.get("f9", 0) or 0,
                            "pb": item.get("f23", 0) or 0
                        }
                    except:
                        continue
            print(f"  批次{i//batch_size+1}: {len(batch)}只 → 获取{len([k for k in batch if k in results])}只")
        except Exception as e:
            print(f"  批次{i//batch_size+1}失败: {e}")
    return results


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
    print(f"[START] 估值共振检查 v3 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})

    # 只查已触发+接近的
    active_codes = [c for c, v in trigger.items() if v.get("status") in ("已触发", "接近")]
    print(f"  待查: {len(active_codes)} 只")

    val_data = get_valuation_batch(active_codes) if active_codes else {}
    print(f"  获取成功: {len(val_data)} 只")

    resonance_hits = []

    for code in active_codes:
        v = trigger[code]
        pe_upper = v.get("pe_upper")
        pb_lower = v.get("pb_lower")
        if not pe_upper and not pb_lower:
            continue

        val = val_data.get(code, {})
        price = val.get("price", 0)
        pe = val.get("pe", 0)
        pb = val.get("pb", 0)

        pe_ok = pb_ok = div_ok = False
        score = 0

        if pe_upper and pe > 0 and pe <= pe_upper:
            pe_ok = True; score += 1
        if pb_lower and pb > 0 and pb <= pb_lower:
            pb_ok = True; score += 1

        dps = v.get("dps", 0)
        anchor = v.get("anchor_pct", 0)
        if dps and anchor and price > 0:
            yld = dps / price * 100
            if yld >= anchor:
                div_ok = True; score += 1

        if score >= 2:
            resonance = "🟢 三振" if score == 3 else "🟢 双振"
        else:
            resonance = "🟡 仅价格"

        trigger[code]["pe_now"] = round(pe, 1) if pe else None
        trigger[code]["pb_now"] = round(pb, 2) if pb else None
        trigger[code]["resonance"] = resonance
        trigger[code]["resonance_score"] = score
        trigger[code]["pe_ok"] = pe_ok
        trigger[code]["pb_ok"] = pb_ok
        trigger[code]["div_ok"] = div_ok

        pe_s = f"PE{pe:.1f}" if pe else "PE?"
        pb_s = f"PB{pb:.2f}" if pb else "PB?"
        print(f"  {v['name']}: {pe_s}(≤{pe_upper}) {pb_s}(≤{pb_lower}) → {resonance}")

        if v.get("status") == "已触发" and score >= 2:
            resonance_hits.append((v["name"], code, price, resonance, score, pe, pe_upper, pb, pb_lower))

    state["trigger"] = trigger
    state["meta"] = state.get("meta", {})
    state["meta"]["updated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    if resonance_hits:
        lines = [f"## 🔬 估值共振 — {now:%Y.%m.%d}", "",
                 f"> {now:%H:%M} | 共振{len(resonance_hits)}只（PE+PB+股息≥2确认）", ""]
        for name, code, price, res, sc, pe, peu, pb, pbl in resonance_hits:
            lines.append(f"**{name}** {res} 得分{sc}/3")
            lines.append(f"> 现价{price:.2f} PE{pe:.1f}(锚≤{peu}) PB{pb:.2f}(锚≤{pbl})")
            lines.append("")
        push(f"🔬 估值共振 {len(resonance_hits)}只 {now:%Y.%m.%d}", "\n".join(lines))

    git_commit_state()
    print(f"[DONE] {len(resonance_hits)}只共振")


if __name__ == "__main__":
    main()
