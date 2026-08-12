"""
Workflow 健康监控 v1
每天 08:30 扫描所有 workflow 最近运行状态 → PushPlus 推送摘要
只关注你的投资系统 workflow，跳过 GitHub 模板自带的
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone

# ── 配置 ──────────────────────────────────────────────
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# 只监控这些 workflow（你的投资系统）
WATCHED = [
    "trigger-monitor.yml",
    "valuation-resonance.yml",
    "sell-monitor.yml",
    "position-control.yml",
    "pnl-watermark.yml",
    "quarterly-report.yml",
    "market-temp.yml",
    "commodity-monitor.yml",
    "shareholder-changes.yml",
    "dividend-calendar.yml",
    "dividend-report.yml",
    "dividend-cash.yml",
    "framework-screening.yml",
    "health-check.yml",
    "trigger-distance.yml",
    "ah-premium.yml",
    "signal-confluence.yml",
    "watchlist-upgrade.yml",
    "sell-signal.yml",
    "performance-attribution.yml",
    "weekly-digest.yml",
    "weekly-report.yml",
    "price-alert.yml",
    "buy-list.yml",
    "cash-planner.yml",
    "position-calibrate.yml",
    "sector-monitor.yml",
    "trigger-adjust.yml",
    "valuation-percentile.yml",
    "calibration.yml",
]

# 预期运行频率
DAILY_WORKDAYS = [
    "trigger-monitor.yml", "valuation-resonance.yml", "sell-monitor.yml",
    "position-control.yml", "pnl-watermark.yml", "quarterly-report.yml",
    "market-temp.yml", "commodity-monitor.yml", "shareholder-changes.yml",
    "dividend-calendar.yml", "price-alert.yml",
]

MONDAY_ONLY = [
    "framework-screening.yml", "dividend-cash.yml", "health-check.yml",
    "trigger-distance.yml", "ah-premium.yml", "signal-confluence.yml",
    "watchlist-upgrade.yml", "performance-attribution.yml",
    "weekly-digest.yml", "buy-list.yml", "cash-planner.yml",
    "position-calibrate.yml", "sector-monitor.yml", "trigger-adjust.yml",
    "valuation-percentile.yml",
]

SUNDAY_ONLY = ["weekly-report.yml"]
WEEKLY = MONDAY_ONLY + SUNDAY_ONLY


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("  [PushPlus] 未配置 TOKEN")
        return
    try:
        r = requests.post(
            "http://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown",
                "topic": PUSHPLUS_TOPIC,
            },
            timeout=10,
        )
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
            print(f"  [API] HTTP {resp.status_code}: {resp.text[:200]}")
            return []
        data = resp.json()
        runs = data.get("workflow_runs", [])
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        for r in runs:
            created = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if created >= cutoff:
                all_runs.append(r)
    except Exception as e:
        print(f"  [API] 异常: {e}")
    return all_runs


def cst_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def main():
    now = cst_now()
    wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    print(f"[START] Workflow 健康监控 v1 {now:%Y-%m-%d} 周{wd}")

    runs = get_recent_runs()
    print(f"  获取到 {len(runs)} 条运行记录（7天内）")

    latest = {}
    for r in runs:
        name = r.get("name", "") or r.get("workflow_name", "")
        if not name:
            name = r.get("path", "").split("/")[-1]
        if name not in latest:
            latest[name] = r

    ok_list, fail_list, unknown_list = [], [], []

    for yml in WATCHED:
        info = latest.get(yml)
        if info is None:
            unknown_list.append(yml)
            continue

        conclusion = info.get("conclusion", "unknown")
        last_run = datetime.strptime(info["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=8)
        days_ago = (now - last_run).days

        if conclusion == "success":
            ok_list.append((yml, last_run, days_ago))
        else:
            fail_list.append((yml, last_run, days_ago, conclusion))

    expected_today = set(DAILY_WORKDAYS)
    if now.weekday() == 0:
        expected_today |= set(MONDAY_ONLY)
    if now.weekday() == 6:
        expected_today |= set(SUNDAY_ONLY)

    missing_today = []
    for yml in expected_today:
        if yml not in latest:
            missing_today.append(yml)
        else:
            last_run = datetime.strptime(latest[yml]["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=8)
            if last_run.date() < now.date():
                missing_today.append(yml)

    lines = [
        f"## 🩺 Workflow 健康 {now:%m.%d} 周{wd}",
        "",
        f"> {len(ok_list)}正常 | {len(fail_list)}失败 | {len(missing_today)}今日缺勤 | {len(unknown_list)}无记录",
        "",
    ]

    if fail_list:
        lines.append("### 🔴 失败")
        lines.append("")
        for yml, last_run, days, _ in fail_list:
            lines.append(f"- `{yml}` — {last_run:%m-%d %H:%M}（{days}天前）❌")
        lines.append("")

    if missing_today and now.weekday() < 5:
        lines.append("### 🟡 今日应跑未跑")
        lines.append("")
        for yml in missing_today:
            lines.append(f"- `{yml}`")
        lines.append("")

    if unknown_list:
        lines.append("### ⚪ 7天内无记录")
        lines.append("")
        for yml in unknown_list:
            lines.append(f"- `{yml}`（从未跑过？yml文件不存在？）")
        lines.append("")

    lines.append("### ✅ 最近正常")
    lines.append("")
    ok_list.sort(key=lambda x: x[2])
    for yml, last_run, days in ok_list:
        if days <= 3:
            lines.append(f"- `{yml}` — {last_run:%m-%d %H:%M}")
        else:
            lines.append(f"- `{yml}` — {last_run:%m-%d}（{days}天前）⚠️")
    lines.append("")

    lines.append(f"---")
    lines.append(f"监控 {len(WATCHED)} 个 | {now:%m-%d %H:%M}")

    push(f"🩺 健康 {now:%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
