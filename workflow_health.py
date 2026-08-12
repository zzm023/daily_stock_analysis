"""
Workflow 健康监控 v2
每天 08:30 扫描你的投资系统 workflow → PushPlus
匹配 Actions 页面的中文名称
"""

import os, json, requests
from datetime import datetime, timedelta, timezone

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# 你的投资系统 workflow（中文名，对应 Actions 页面）
WATCHED = [
    "触发价监控",
    "估值共振检查",
    "卖出决策仪表盘",
    "仓位风控",
    "持仓损益水印",
    "季报追踪",
    "全市场估值温度",
    "大宗商品监控",
    "大股东增减持",
    "股息日历",
    "股息率周报",
    "分红金额预测",
    "框架全量筛选",
    "持仓九宫格",
    "触发价动态调整",
    "AH溢价监控",
    "多信号共振",
    "观察清单升级",
    "卖出信号",
    "业绩归因周报",
    "周一汇总",
    "周末汇总周报",
    "价格异动监控",
    "买入清单",
    "现金规划",
    "仓位校准",
    "行业集中度",
    "估值分位数",
    "状态校准",
    "每周复盘",
    "复盘笔记",
    "压力测试",
    "主力资金哨兵",
    "股息复利推演",
    "利润缓存",
    "持仓日报",
    "Workflow 健康监控",
]

DAILY = [
    "触发价监控", "估值共振检查", "卖出决策仪表盘", "仓位风控",
    "持仓损益水印", "季报追踪", "全市场估值温度", "大宗商品监控",
    "大股东增减持", "股息日历", "价格异动监控",
]

MONDAY = [
    "框架全量筛选", "分红金额预测", "持仓九宫格", "AH溢价监控",
    "多信号共振", "观察清单升级", "业绩归因周报", "周一汇总",
    "买入清单", "现金规划", "仓位校准", "行业集中度",
    "触发价动态调整", "估值分位数", "股息率周报",
]

SUNDAY = ["周末汇总周报"]


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
    url = f"https://api.github.com/repos/{REPO}/actions/runs?per_page=100"
    all_runs = []
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"  [API] HTTP {resp.status_code}")
            return []
        runs = resp.json().get("workflow_runs", [])
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        for r in runs:
            t = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if t >= cutoff:
                all_runs.append(r)
    except Exception as e:
        print(f"  [API] 异常: {e}")
    return all_runs


def cst_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def main():
    now = cst_now()
    wd = ["一","二","三","四","五","六","日"][now.weekday()]
    print(f"[START] v2 {now:%Y-%m-%d} 周{wd}")

    runs = get_recent_runs()
    print(f"  API返回 {len(runs)} 条")

    # 按 name 分组取最新
    latest = {}
    for r in runs:
        name = r.get("name", "")
        if name and (name not in latest):
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
        if conclusion == "success":
            ok_list.append((name, t, days))
        else:
            fail_list.append((name, t, days, conclusion))

    # 今天该跑但没跑
    expected = set(DAILY)
    if now.weekday() == 0:
        expected |= set(MONDAY)
    if now.weekday() == 6:
        expected |= set(SUNDAY)
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
        for name, t, days, _ in fail_list:
            lines.append(f"- {name} — {t:%m-%d %H:%M}（{days}天前）❌")
        lines.append("")

    if missing and now.weekday() < 5:
        lines.append("### 🟡 今日应跑未跑")
        for name in missing:
            lines.append(f"- {name}")
        lines.append("")

    if unseen:
        lines.append("### ⚪ 7天内无记录")
        for name in unseen:
            lines.append(f"- {name}（yml不存在或从未跑过）")
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
