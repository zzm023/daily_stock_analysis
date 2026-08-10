#!/usr/bin/env python3
"""
估值共振检查 v2
数据源：akshare PE/PB + 新浪价格兜底
每日 16:15 CST（触发价监控之后）
"""
import os
import re
import json
import requests
import subprocess
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_all_valuation():
    """akshare 全量拉取 PE/PB/现价"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        lookup = {}
        for _, row in df.iterrows():
            code = row["代码"]
            try:
                lookup[code] = {
                    "price": float(row["最新价"]),
                    "pe": float(row["市盈率-动态"]) if row["市盈率-动态"] and str(row["市盈率-动态"]) != "-" else 0,
                    "pb": float(row["市净率"]) if row["市净率"] and str(row["市净率"]) != "-" else 0
                }
            except:
                continue
        return lookup
    except Exception as e:
        print(f"[akshare] 失败: {e}")
        return {}


def get_single_price(code):
    """腾讯兜底"""
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=5)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) >= 4:
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
    print(f"[START] 估值共振检查 v2 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    val_data = get_all_valuation()
    print(f"  akshare 获取 {len(val_data)} 只")

    resonance_hits = []

    for code, v in trigger.items():
        status = v.get("status", "")
        if status not in ("已触发", "接近"):
            continue

        pe_upper = v.get("pe_upper")
        pb_lower = v.get("pb_lower")
        if not pe_upper and not pb_lower:
            continue

        val = val_data.get(code, {})
        price = val.get("price", 0)
        pe = val.get("pe", 0)
        pb = val.get("pb", 0)

        if price == 0:
            price = get_single_price(code)

        pe_ok = pb_ok = div_ok = False
        score = 0

        if pe_upper and pe > 0 and pe <= pe_upper:
            pe_ok = True
            score += 1

        if pb_lower and pb > 0 and pb <= pb_lower:
            pb_ok = True
            score += 1

        dps = v.get("dps", 0)
        anchor = v.get("anchor_pct", 0)
        if dps and anchor and price > 0:
            yld = dps / price * 100
            if yld >= anchor:
                div_ok = True
                score += 1

        if score >= 2:
            resonance = "🟢 三振" if score == 3 else "🟢 双振"
        else:
            resonance = "🟡 仅价格"

        trigger[code]["pe_now"] = round(pe, 1)
        trigger[code]["pb_now"] = round(pb, 2)
        trigger[code]["resonance"] = resonance
        trigger[code]["resonance_score"] = score
        trigger[code]["pe_ok"] = pe_ok
        trigger[code]["pb_ok"] = pb_ok
        trigger[code]["div_ok"] = div_ok

        pe_info = f"PE{pe:.1f}(≤{pe_upper})" if pe else f"PE?(≤{pe_upper})"
        pb_info = f"PB{pb:.2f}(≤{pb_lower})" if pb else f"PB?(≤{pb_lower})"
        print(f"  {v['name']}: {pe_info} {pb_info} → {resonance}")

        if status == "已触发" and score >= 2:
            resonance_hits.append((v["name"], code, price, resonance, score, pe, pe_upper, pb, pb_lower))

    state["trigger"] = trigger
    state["meta"] = state.get("meta", {})
    state["meta"]["updated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    if resonance_hits:
        lines = [f"## 🔬 估值共振 — {now:%Y.%m.%d}", "",
                 f"> {now:%H:%M} | 共振{len(resonance_hits)}只（PE+PB+股息至少双确认）", ""]
        for name, code, price, res, sc, pe, peu, pb, pbl in resonance_hits:
            lines.append(f"**{name}** {res} 得分{sc}/3")
            lines.append(f"> 现价{price:.2f} PE{pe:.1f}(锚≤{peu}) PB{pb:.2f}(锚≤{pbl})")
            lines.append("")
        push(f"🔬 估值共振 {len(resonance_hits)}只 {now:%Y.%m.%d}", "\n".join(lines))

    git_commit_state()
    print(f"[DONE] {len(resonance_hits)}只共振")


if __name__ == "__main__":
    main()
