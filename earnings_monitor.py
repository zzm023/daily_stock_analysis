"""
季报追踪 v1.0（任务④）
功能：持仓股业绩预告 + 基本面恶化预警
数据源：Tushare（forecast业绩预告 + income利润表）
联动：恶化写入 earnings_events，卖出决策自动读
运行：收盘后 16:45
"""

import os, json, time, requests
from datetime import datetime, timedelta, timezone

import tushare as ts

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
FRAMEWORK_FILE = "framework_state.json"

BAD_TYPES = {"预减", "略减", "预亏", "首亏", "增亏", "续亏"}   # 恶化预告类型
EXCLUDE = {"002747"}   # 埃斯顿


def to_tscode(code):
    if code.startswith(("6", "9")):
        return code + ".SH"
    return code + ".SZ"


def load_holdings():
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {}
    return {k: v for k, v in data.get("holdings", {}).items() if k != "cash"}


def save_earnings_events(events):
    try:
        with open(FRAMEWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        data = {}
    data["earnings_events"] = events
    data.setdefault("meta", {})["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(FRAMEWORK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        r = requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title,
            "content": content, "template": "markdown",
            "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
        print(f"  [Push] {'OK' if r.json().get('code') == 200 else r.json()}")
    except Exception as e:
        print(f"  [Push] {e}")


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 季报追踪 {now:%m-%d %H:%M}")

    if not TUSHARE_TOKEN:
        print("[SKIP] 未配置 TUSHARE_TOKEN")
        return

    pro = ts.pro_api(TUSHARE_TOKEN)
    holdings = load_holdings()

    positions = []
    for code, info in holdings.items():
        if code in EXCLUDE:
            continue
        positions.append({"code": code, "name": info.get("name", code)})

    if not positions:
        push(f"📊 季报追踪 {now:%m-%d}", "## 季报追踪\n\n无持仓。")
        return

    worsen = []
    normal = []
    no_data = []

    for p in positions:
        code = p["code"]
        tscode = to_tscode(code)
        name = p["name"]
        bad = False
        detail = []

        # 1. 业绩预告
        try:
            df_f = pro.forecast(ts_code=tscode, start_date='20250101', end_date='20261231',
                                fields='ts_code,ann_date,end_date,type')
            if df_f is not None and not df_f.empty:
                df_f = df_f.sort_values("ann_date")
                row = df_f.iloc[-1]
                ftype = str(row.get("type", ""))
                ann = str(row.get("ann_date", ""))[:10]
                if ftype in BAD_TYPES:
                    bad = True
                    detail.append(f"预告:{ftype}")
                elif ftype:
                    detail.append(f"预告:{ftype}")
        except Exception as e:
            print(f"  {name} 预告失败: {e}")
        time.sleep(0.3)

        # 2. 利润表同比
        try:
            df_i = pro.income(ts_code=tscode, start_date='20240101', end_date='20261231',
                              fields='ts_code,end_date,revenue,n_income_attr_p')
            if df_i is not None and not df_i.empty:
                df_i = df_i.sort_values("end_date")
                latest = df_i.iloc[-1]
                cur_end = str(latest["end_date"])
                ly_end = str(int(cur_end[:4]) - 1) + cur_end[4:]
                ly = df_i[df_i["end_date"].astype(str) == ly_end]
                if not ly.empty:
                    cur_ni = float(latest.get("n_income_attr_p", 0) or 0)
                    ly_ni = float(ly.iloc[0].get("n_income_attr_p", 0) or 0)
                    cur_rev = float(latest.get("revenue", 0) or 0)
                    ly_rev = float(ly.iloc[0].get("revenue", 0) or 0)
                    if ly_ni != 0:
                        ni_g = (cur_ni - ly_ni) / abs(ly_ni) * 100
                        detail.append(f"净利同比{ni_g:+.1f}%")
                        if ni_g < -20:
                            bad = True
                    if ly_rev != 0:
                        rev_g = (cur_rev - ly_rev) / abs(ly_rev) * 100
                        detail.append(f"营收同比{rev_g:+.1f}%")
                        if rev_g < -10:
                            bad = True
        except Exception as e:
            print(f"  {name} 利润表失败: {e}")
        time.sleep(0.3)

        if not detail:
            no_data.append((name, code))
        elif bad:
            worsen.append((name, code, " ".join(detail)))
        else:
            normal.append((name, code, " ".join(detail)))

    # 写 earnings_events（联动卖出决策）
    events = []
    for name, code, d in worsen:
        events.append({"code": code, "name": name, "status": "恶化", "detail": d})
    save_earnings_events(events)

    print(f"  恶化 {len(worsen)} | 正常 {len(normal)} | 无数据 {len(no_data)}")

    lines = [
        f"## 📊 季报追踪 {now:%m-%d %H:%M}",
        f"持仓{len(positions)}只 · 恶化{len(worsen)} · 正常{len(normal)} · 无数据{len(no_data)}",
        "",
    ]

    if worsen:
        lines.append("**🔴 基本面恶化（联动卖出决策）**")
        lines.append("")
        for name, code, d in worsen:
            lines.append(f"· {name}({code}) {d}")
            lines.append("")

    if normal:
        lines.append("**🟢 正常**")
        lines.append("")
        for name, code, d in normal:
            lines.append(f"· {name}({code}) {d}")
            lines.append("")

    if no_data:
        lines.append("**⚪ 无财报数据**")
        lines.append("")
        for name, code in no_data:
            lines.append(f"· {name}({code})")
            lines.append("")

    lines.append("⚠️ 恶化清单已写入 earnings_events，卖出决策自动读取并警示。")

    push(f"📊 季报追踪（恶化{len(worsen)}）", "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
