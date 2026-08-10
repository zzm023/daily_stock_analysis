"""
季报追踪 v1
检查持仓+框架股票：即将披露 / 已披露但恶化
数据源：东方财富 API（无 akshare 依赖）
"""
import os
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


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


def get_report_schedule():
    try:
        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        params = {
            "reportName": "RPT_DMSK_FN_DISCLOSURETIME",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,PERIOD",
            "pageSize": 200,
            "sortColumns": "NOTICE_DATE",
            "sortTypes": 1,
            "source": "WEB",
            "client": "WEB",
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("success"):
            return data["result"]["data"]
    except Exception as e:
        print(f"  财报日程获取失败: {e}")
    return []


def get_financial_summary(code):
    try:
        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        params = {
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "SECURITY_CODE,NOTICE_DATE,REPORT_DATE,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,"
                       "SJLTZ_TOTAL_OPERATE_INCOME,SJLTZ_PARENT_NETPROFIT",
            "filter": f'(SECURITY_CODE="{code}")',
            "pageSize": 3,
            "sortColumns": "REPORT_DATE",
            "sortTypes": -1,
            "source": "WEB",
            "client": "WEB",
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("success") and data["result"]["data"]:
            return data["result"]["data"][0]
    except Exception as e:
        print(f"  财报摘要 {code} 失败: {e}")
    return None


def main():
    now = datetime.now()
    print(f"[START] 季报追踪 v1 {now:%Y-%m-%d %H:%M}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    monitor_codes = set()
    for code in hold:
        if code != "cash" and isinstance(hold.get(code), dict):
            monitor_codes.add(code)
    for code, v in trigger.items():
        if v.get("status") in ("已触发", "接近"):
            monitor_codes.add(code)

    print(f"  监控 {len(monitor_codes)} 只")

    schedules = get_report_schedule()
    code_to_date = {}
    for s in schedules:
        code_to_date[s["SECURITY_CODE"]] = s

    upcoming = []
    deteriorated = []
    cutoff = now + timedelta(days=14)

    for code in monitor_codes:
        name = ""
        for src in [hold, trigger]:
            v = src.get(code)
            if v and isinstance(v, dict):
                name = v.get("name", code)
                break
        if not name:
            name = code

        sched = code_to_date.get(code)
        if sched:
            try:
                notice_date = datetime.strptime(sched["NOTICE_DATE"][:10], "%Y-%m-%d")
                period = sched.get("PERIOD", "")
                if notice_date <= cutoff and notice_date >= now:
                    upcoming.append({
                        "name": name, "code": code,
                        "date": sched["NOTICE_DATE"][:10],
                        "period": period,
                    })
            except:
                pass

        fin = get_financial_summary(code)
        if fin:
            try:
                rev = fin.get("TOTAL_OPERATE_INCOME")
                profit = fin.get("PARENT_NETPROFIT")
                rev_yoy = fin.get("SJLTZ_TOTAL_OPERATE_INCOME")
                profit_yoy = fin.get("SJLTZ_PARENT_NETPROFIT")

                if rev and profit and rev_yoy is not None and profit_yoy is not None:
                    rev = float(rev)
                    profit = float(profit)
                    rev_yoy = float(rev_yoy)
                    profit_yoy = float(profit_yoy)

                    issues = []
                    if profit < 0:
                        issues.append("由盈转亏")
                    elif profit_yoy < -20:
                        issues.append(f"利润同比{profit_yoy:+.1f}%")
                    if rev_yoy < -10:
                        issues.append(f"营收同比{rev_yoy:+.1f}%")

                    if issues:
                        deteriorated.append({
                            "name": name, "code": code,
                            "report_date": fin.get("REPORT_DATE", "")[:10],
                            "rev_yoy": f"{rev_yoy:+.1f}%",
                            "profit_yoy": f"{profit_yoy:+.1f}%",
                            "issues": issues,
                        })
            except:
                pass

    if not upcoming and not deteriorated:
        print("[DONE] 无新报告日程，无恶化")
        return

    lines = [f"## 📊 季报追踪 — {now:%Y.%m.%d}", "",
             f"{now:%H:%M} | 监控{len(monitor_codes)}只", ""]

    if upcoming:
        lines.append("### 📅 近期披露（2周内）")
        lines.append("")
        for u in sorted(upcoming, key=lambda x: x["date"]):
            lines.append(f"- **{u['name']}**（{u['code']}） {u['date']} | {u['period']}")
        lines.append("")

    if deteriorated:
        lines.append("### 🔴 财报恶化")
        lines.append("")
        for d in deteriorated:
            lines.append(f"**{d['name']}**（{d['code']}） {d['report_date']}")
            lines.append(f"> 营收同比{d['rev_yoy']} | 利润同比{d['profit_yoy']}")
            lines.append(f"> ⚠️ {', '.join(d['issues'])}")
            lines.append("")

    push(f"📊 季报追踪 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 近期披露{len(upcoming)}只 恶化{len(deteriorated)}只")


if __name__ == "__main__":
    main()
