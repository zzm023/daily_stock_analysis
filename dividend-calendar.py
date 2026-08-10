"""
股息日历 v1
追踪框架股+持仓股：除权除息日 / 每股分红 / 到账日
每日推送未来 30 天内的股息事件
"""
import os
import json
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_dividend_schedule():
    """东方财富：未来股息日历"""
    try:
        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        params = {
            "reportName": "RPT_DMSK_FN_EXRW",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,EX_DIVIDEND_DATE,PLAN_EXPLAIN,"
                       "PAYMENT_DATE,DIVIDEND_PLAN_DATE,CASH_DIVIDEND",
            "pageSize": 200,
            "sortColumns": "EX_DIVIDEND_DATE",
            "sortTypes": 1,
            "source": "WEB",
            "client": "WEB",
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("success"):
            return data["result"]["data"]
    except Exception as e:
        print(f"  股息日历获取失败: {e}")
    return []


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    today = date.today()
    cutoff = today + timedelta(days=30)

    print(f"[START] 股息日历 v1 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    # 需要监控的股票
    monitor_codes = set()
    for code in hold:
        if code != "cash" and isinstance(hold.get(code), dict):
            monitor_codes.add(code)
    for code in trigger:
        if isinstance(trigger.get(code), dict):
            monitor_codes.add(code)

    schedules = get_dividend_schedule()

    ex_rights = []      # 即将除权
    upcoming_pay = []   # 即将到账
    just_passed = []    # 最近3天已除权（可买入收息？）

    for s in schedules:
        code = s["SECURITY_CODE"]
        if code not in monitor_codes:
            continue

        name = s.get("SECURITY_NAME_ABBR", code)
        ex_date_str = s.get("EX_DIVIDEND_DATE", "")
        pay_date_str = s.get("PAYMENT_DATE", "")
        cash_div = s.get("CASH_DIVIDEND") or 0

        try:
            cash_div = float(cash_div)
        except:
            cash_div = 0

        if ex_date_str:
            try:
                ex_date = datetime.strptime(ex_date_str[:10], "%Y-%m-%d").date()
                if today <= ex_date <= cutoff:
                    ex_rights.append({
                        "name": name, "code": code,
                        "ex_date": ex_date_str[:10],
                        "cash_div": cash_div,
                        "pay_date": pay_date_str[:10] if pay_date_str else "?",
                    })
                elif today - timedelta(days=3) <= ex_date < today:
                    just_passed.append({
                        "name": name, "code": code,
                        "ex_date": ex_date_str[:10],
                        "cash_div": cash_div,
                    })
            except:
                pass

        if pay_date_str:
            try:
                pay_date = datetime.strptime(pay_date_str[:10], "%Y-%m-%d").date()
                if today <= pay_date <= cutoff:
                    upcoming_pay.append({
                        "name": name, "code": code,
                        "pay_date": pay_date_str[:10],
                        "cash_div": cash_div,
                    })
            except:
                pass

    if not ex_rights and not upcoming_pay and not just_passed:
        print("[DONE] 未来30天无股息事件")
        return

    lines = [f"## 💰 股息日历 — {today:%m.%d}-{(today+timedelta(days=30)):%m.%d}", "",
             f"{now:%H:%M} | 监控{len(monitor_codes)}只", ""]

    if ex_rights:
        lines.append("### 📅 即将除权（30天内）")
        lines.append("")
        for d in sorted(ex_rights, key=lambda x: x["ex_date"]):
            lines.append(f"**{d['name']}**（{d['code']}）")
            lines.append(f"> 除权日 {d['ex_date']} | 每股{d['cash_div']:.2f}元 | 到账 {d['pay_date']}")
            # 判断是否在持仓中
            hv = hold.get(d['code'])
            if hv and isinstance(hv, dict) and hv.get("cost", 0) > 0:
                cost = hv["cost"]
                yld = d["cash_div"] / cost * 100 if cost else 0
                lines.append(f"> 🎯 持仓成本息率{yld:.1f}%")
            lines.append("")
    else:
        lines.append("### 📅 即将除权")
        lines.append("无。")
        lines.append("")

    if upcoming_pay:
        lines.append("### 💵 即将到账")
        lines.append("")
        for d in sorted(upcoming_pay, key=lambda x: x["pay_date"]):
            lines.append(f"**{d['name']}** {d['pay_date']}到账 每股{d['cash_div']:.2f}元")
            lines.append("")
    else:
        lines.append("### 💵 即将到账")
        lines.append("无。")
        lines.append("")

    if just_passed:
        lines.append("### 📌 近期已除权（3天内）")
        lines.append("除权后股价下修，若触发价到位可关注。")
        for d in just_passed:
            lines.append(f"- **{d['name']}** {d['ex_date']} 除权 每股{d['cash_div']:.2f}元")
        lines.append("")

    lines.append("---")
    lines.append("📌 股息再投时机：除权后股价自然下修 + 到账日有资金 = 可配合触发价分层买入。")
    push(f"💰 股息日历 {today:%m.%d}-{(today+timedelta(days=30)):%m.%d}", "\n".join(lines))
    print("[DONE]")


if __name__ == "__main__":
    main()
