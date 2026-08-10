"""
触发价监控 v3
数据源：腾讯 qt.gtimg.cn | 读/写 framework_state.json
每日 15:00 CST
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


def git_commit_state():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", "framework_state.json"], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "[auto] 更新触发价状态"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("[GIT] framework_state.json 已提交")
    except Exception as e:
        print(f"[GIT] 提交失败: {e}")


def main():
    now = datetime.now()
    print(f"[START] 触发价监控 v3 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hit, close = [], []
    fail = 0

    for code, v in trigger.items():
        trigger_price = v.get("trigger_price", 0)
        if not trigger_price:
            continue

        price = get_price(code)
        if price == 0:
            fail += 1
            continue

        gap = (price - trigger_price) / trigger_price * 100

        if price <= trigger_price:
            status = "已触发"
            hit.append((code, v["name"], price, trigger_price, abs(gap)))
        elif gap <= 10:
            status = "接近"
            close.append((code, v["name"], price, trigger_price, abs(gap)))
        else:
            status = "远离"

        trigger[code]["current_price"] = round(price, 2)
        trigger[code]["gap_pct"] = round(gap, 1)
        trigger[code]["status"] = status

        if status in ("已触发", "接近"):
            print(f"  {v['name']}({code}) 现{price:.2f} 触发{trigger_price:.2f} 距{gap:+.1f}% {status}")
        else:
            # 仅打印接近/触发
            pass

    state["trigger"] = trigger
    state["meta"] = state.get("meta", {})
    state["meta"]["updated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"  已触发{len(hit)} 接近{len(close)} 失败{fail}")

    if hit or close:
        lines = [f"## 触发价监控 — {now:%Y.%m.%d}", "",
                 f"{now:%H:%M} | 已触发{len(hit)}只 接近{len(close)}只", ""]
        if hit:
            lines.append("### 已触发")
            for c, n, p, t, g in hit:
                lines.append(f"{n} {p:.2f}（触发价{t:.2f}，超{g:.1f}%）")
            lines.append("")
        if close:
            lines.append(f"### 即将触发（≤10%）")
            for c, n, p, t, g in close:
                lines.append(f"{n} {p:.2f}（触发价{t:.2f}，差{g:.1f}%）")
            lines.append("")
        lines.append("⚠️ 触发≠买。左侧分层，目标价9折，仓位减半，观察1周。")
        push(f"触发{len(hit)}只 {now:%Y.%m.%d}", "\n".join(lines))

    git_commit_state()
    print(f"[DONE] {len(hit)}触发 {len(close)}接近")


if __name__ == "__main__":
    main()
