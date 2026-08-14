#!/usr/bin/env python3
"""
DPS 全年口径校验（一次性，跑完删）
用 Tushare dividend 拉全年 DPS，对比 framework_state.json 当前值
"""
import os
import json
import requests
import tushare

STATE_FILE = "framework_state.json"
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def to_ts_code(code):
    if code.startswith("6"):
        return code + ".SH"
    elif code.startswith(("0", "3")):
        return code + ".SZ"
    elif code.startswith(("8", "4")):
        return code + ".BJ"
    return code


def get_annual_dps(pro, code):
    """按分红年度分组，取最近完整年度 sum(cash_div)"""
    try:
        df = pro.dividend(ts_code=to_ts_code(code),
                          fields="end_date,cash_div")
        if df is None or df.empty:
            return None
        df = df.dropna(subset=["cash_div"])
        if df.empty:
            return None
        df["year"] = df["end_date"].astype(str).str[:4]
        annual = df.groupby("year")["cash_div"].sum()
        return float(annual.iloc[-1])
    except Exception as e:
        print(f"  [{code}] {e}")
        return None


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print(content)
        return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title,
                   "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    except Exception as e:
        print(f"[Push] {e}")


def main():
    if not TUSHARE_TOKEN:
        print("未配置 TUSHARE_TOKEN")
        return
    pro = tushare.pro_api(TUSHARE_TOKEN)

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    trigger = state.get("trigger", {})

    lines = ["## 🔍 DPS 全年口径校验", ""]
    wrong = []

    for code, info in trigger.items():
        if not isinstance(info, dict):
            continue
        dps = info.get("dps", 0)
        if not dps:
            continue
        name = info.get("name", code)
        annual = get_annual_dps(pro, code)

        if annual is None:
            lines.append(f"- {name}({code}) 当前 {dps} | 查不到全年数据")
            continue

        diff = abs(annual - dps)
        if diff < 0.05:
            lines.append(f"- ✅ {name}({code}) {dps} 正确")
        else:
            wrong.append((name, code, dps, annual))
            lines.append(f"- ❌ {name}({code}) 当前 {dps} → 应为 {annual}")

    lines.append("")
    if wrong:
        lines.append(f"**需修正 {len(wrong)} 只：**")
        for name, code, dps, annual in wrong:
            lines.append(f"- {name}({code}): `{dps}` → `{annual}`")
    else:
        lines.append("全部正确 ✅")

    push("DPS校验结果", "\n".join(lines))
    print("完成")


if __name__ == "__main__":
    main()
