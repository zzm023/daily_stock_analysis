"""
Workflow 健康监控 v4
每天 21:00（收盘后）扫描 workflow → PushPlus
v4：收盘后检查 + 周末不查每日任务 + 只把failure算失败 + 拉全7天
"""
import os, json, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

DAILY = [
    "触发价监控", "估值共振检查", "卖出决策·翻倍+回本+恶化", "仓位风控",
    "持仓损益水印", "季报追踪", "全市场估值温度", "大宗商品监控",
    "大股东增减持", "股息日历", "价格异动监控",
    "复盘笔记", "主力资金哨兵", "持仓日报", "股息收租·日历+现金流",
    "估值共振·PE/PB达标判断",
]

WEEKLY = {
    0: ["框架扫描", "触发价追溯", "股息率周报", "持仓体检·仓位风控",
        "状态校准", "股息复利推演"],                              # 周一
    1: ["框架全量筛选", "现金规划"],                             # 周二
    2: ["估值分位数", "观察清单升级"],                           # 周三
    3: ["行业集中度", "业绩归因周报"],                           # 周四
    4: ["AH溢价监控", "周度汇总"],                               # 周五
    5: ["每周复盘"],                                            # 周六
    6: ["周末汇总周报"],                                        # 周日
}

WATCHED = DAILY + [n for names in WEEKLY.values() for n in names]


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        r = requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title,
            "content": content, "template": "markdown",
            "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
        print(f"  [PushPlus] {'✅' if r.json().get('code') == 200 else r.json()}")
    except Exception as e:
        print(f"  [PushPlus] 异常: {e}")


def get_recent_runs():
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    all_runs = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for page in range(1, 4):
        url = f"https://api.github.com/repos/{REPO}/actions/runs?per_page=100&page={page}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                break
            runs = resp.json().get("workflow_runs", [])
            if not runs:
                break
            stop = False
            for r in runs:
                t = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if t < cutoff:
                    stop = True
                    break
                all_runs.append(r)
            if stop:
                break
        except Exception as e:
            print(f"  [API] page{page} 异常: {e}")
            break
    return all_runs


def cst_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def main():
    now = cst_now()
    wd = ["一","二","三","四","五","六","日"][now.weekday()]
    print(f"[START] v4 {now:%Y-%m-%d} 周{wd}")

    runs = get_recent_runs()
    print(f"  API返回 {len(runs)} 条")

    latest = {}
    for r in runs:
        name = r.get("name", "")
        if name and name not in latest:
            latest[name] = r

    ok_list, fail_list, missing, unseen = [], [], [], []

    for name in WATCHED:
        info = latest.get(name)
        if info is None:
            unseen.append(name)
            continue
        conclusion = info.get("conclusion", "unknown")
        t = datetime.strptime(info["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=8)
        days = (now - t).days
        if conclusion == "failure":
            fail_list.append((name, t, days))
        else:
            ok_list.append((name, t, days))

    # 今天该跑但没跑：工作日=每日+当天周度；周末=只查当天周度
    expected = set(WEEKLY.get(now.weekday(), []))
    if now.weekday() < 5:
        expected |= set(DAILY)

    for name in expected:
        if name not in latest:
            missing.append(name)
        else:
            t = datetime.strptime(latest[name]["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=8)
            if t.date() < now.date():
                missing.append(name)

    lines = [
        f"## 🩺 健康 {now:%m.%d} 周{wd}",
        f"> {len(ok_list)}✅ | {len(fail_list)}🔴 | {len(missing)}🟡缺勤 | {len(unseen)}⚪无记录",
        "",
    ]

    if fail_list:
        lines.append("### 🔴 失败")
        for name, t, days in fail_list:
            lines.append(f"- {name} — {t:%m-%d %H:%M}（{days}天前）❌")
        lines.append("")

    if missing:
        lines.append("### 🟡 今日应跑未跑")
        for name in missing:
            lines.append(f"- {name}")
        lines.append("")

    if unseen:
        lines.append("### ⚪ 7天内无记录")
        for name in unseen:
            lines.append(f"- {name}（名字对不上或从未跑过）")
        lines.append("")

    ok_list.sort(key=lambda x: x[2])
    lines.append("### ✅ 最近运行")
    for name, t, days in ok_list:
        lines.append(f"- {name} — {t:%m-%d %H:%M}" + (f" ⚠️{days}天前" if days > 3 else ""))
    lines.append("")
    lines.append(f"---")
    lines.append(f"监控 {len(WATCHED)} 个 | {now:%m-%d %H:%M}")

    push(f"🩺 健康 {now:%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
