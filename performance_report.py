"""
业绩归因周报 v1
每周记录总资产/沪深300 → 累计收益/超额收益/个股贡献
"""
import os
import json
import requests
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

STATE_FILE = Path(__file__).parent / "framework_state.json"
SNAP_FILE = Path(__file__).parent / "performance_snapshots.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def batch_tencent(codes):
    results = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i + 30]
        symbols = ",".join(
            f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch
        )
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if not m:
                    continue
                parts = m.group().split("~")
                if len(parts) < 48:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else None
                    if price:
                        results[c] = {"price": price, "name": parts[1]}
                except Exception:
                    pass
        except Exception:
            pass
    return results


def get_csi300():
    """沪深300 点位"""
    try:
        r = requests.get("http://qt.gtimg.cn/q=sh000300", timeout=10)
        r.encoding = "gbk"
        m = re.search(r'v_sh000300="[^"]*"', r.text)
        if m:
            parts = m.group().split("~")
            return float(parts[3]) if parts[3] else None
    except Exception:
        pass
    return None


def push(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        requests.post(
            "http://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown",
                "topic": PUSHPLUS_TOPIC,
            },
            timeout=10
        )
    except Exception:
        pass


def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    print(f"[START] 业绩归因 v1 {today}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    cash = hold.get("cash", 0)
    hold_codes = [c for c in hold if c != "cash" and isinstance(hold.get(c), dict)]

    # 现价
    quotes = batch_tencent(hold_codes)
    csi300 = get_csi300()

    # 算总资产
    total_mv = cash
    holdings_detail = {}
    for code in hold_codes:
        v = hold[code]
        q = quotes.get(code, {})
        price = q.get("price", v.get("cost", 0))
        shares = v.get("shares", 0)
        mv = price * shares
        total_mv += mv
        holdings_detail[code] = {
            "name": q.get("name", v.get("name", code)),
            "price": price,
            "shares": shares,
            "mv": mv,
        }

    # 读历史快照
    snapshots = {}
    if SNAP_FILE.exists():
        with open(SNAP_FILE, "r", encoding="utf-8") as f:
            snapshots = json.load(f)

    # 存本周快照
    snapshots[today] = {
        "total_mv": total_mv,
        "cash": cash,
        "csi300": csi300,
        "holdings": holdings_detail,
    }

    # 只保留最近 52 周
    keys = sorted(snapshots.keys())
    if len(keys) > 52:
        for old_key in keys[:-52]:
            del snapshots[old_key]

    with open(SNAP_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)

    # --- 计算 ---
    dates = sorted(snapshots.keys())
    first_date = dates[0]
    first = snapshots[first_date]

    lines = [
        f"业绩归因 {now:%m}.{now:%d}",
        f"总资产 {total_mv/10000:.1f}万 | 现金 {cash/10000:.1f}万",
    ]

    # 基准
    if csi300 and first.get("csi300"):
        csi_chg = (csi300 - first["csi300"]) / first["csi300"] * 100
        csi_first = first["csi300"]
        lines.append(f"沪深300 {csi300:.0f} | 基准日({first_date}) {csi_first:.0f}")
        lines.append(f"基准变动 {csi_chg:+.1f}%")
    elif csi300:
        lines.append(f"沪深300 {csi300:.0f}")

    # 累计收益
    if len(dates) >= 2:
        cumulative_chg = (total_mv - first["total_mv"]) / first["total_mv"] * 100
        lines.append("")
        lines.append(f"◆ 累计 ({first_date} → {today})")
        lines.append(f"总资产变动 {cumulative_chg:+.1f}%")

        # 超额
        if csi300 and first.get("csi300"):
            csi_chg = (csi300 - first["csi300"]) / first["csi300"] * 100
            alpha = cumulative_chg - csi_chg
            sign = "跑赢" if alpha > 0 else "跑输"
            lines.append(f"超额 {alpha:+.1f}%  {sign}沪深300")

        # 周环比
        if len(dates) >= 2:
            prev = snapshots[dates[-2]]
            week_chg = (total_mv - prev["total_mv"]) / prev["total_mv"] * 100
            lines.append(f"本周变动 {week_chg:+.2f}%")
    else:
        lines.append("")
        lines.append("首周基准已建立，下周起显示收益")

    # 个股贡献
    lines.append("")
    lines.append("◆ 持仓")
    holdings_sorted = sorted(
        holdings_detail.items(), key=lambda x: x[1]["mv"], reverse=True
    )
    for code, d in holdings_sorted:
        pct = d["mv"] / total_mv * 100 if total_mv > 0 else 0
        lines.append(f"- {d['name']} {d['price']:.2f}×{d['shares']} = {d['mv']/10000:.2f}万 ({pct:.0f}%)")

    # 收益预估
    lines.append("")
    lines.append("> 每周一快照 | 首周建立基准无比较")

    push(f"业绩归因 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE] 快照{sorted(snapshots.keys())}")


if __name__ == "__main__":
    main()
