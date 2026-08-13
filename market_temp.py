#!/usr/bin/env python3
"""
全市场估值温度 v2（任务⑩）
功能：沪深300 PE(TTM) 历史分位 → 大盘温度计
数据源：Tushare index_dailybasic（指数每日指标，含PE/PB）
运行：收盘后 17:00
"""

import os
import requests
from datetime import datetime, timezone, timedelta
import tushare as ts

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("  [PushPlus] 未配置TOKEN，跳过推送")
        return
    try:
        payload = {
            "token": PUSHPLUS_TOKEN,
            "title": title,
            "content": content,
            "template": "markdown",
        }
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        result = r.json()
        if result.get("code") == 200:
            print(f"  [PushPlus] 推送成功")
        else:
            print(f"  [PushPlus] 推送失败: {result}")
    except Exception as e:
        print(f"  [PushPlus] 推送异常: {e}")


def percentile_rank(series, value):
    if len(series) == 0:
        return None
    below = (series <= value).sum()
    return round(below / len(series) * 100, 1)


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 全市场温度 {now:%m-%d %H:%M}")

    if not TUSHARE_TOKEN:
        print("[SKIP] 未配置 TUSHARE_TOKEN")
        return

    try:
        pro = ts.pro_api(TUSHARE_TOKEN)
        end = now.strftime("%Y%m%d")
        start = "20100101"

        df = pro.index_dailybasic(ts_code="000300.SH", start_date=start, end_date=end,
                                  fields="ts_code,trade_date,pe,pe_ttm,pb")

        if df is None or df.empty:
            print("  沪深300 PE 数据为空（可能积分不足）")
            push("🌡️ 全市场温度", "## 🌡️ 全市场温度\n\n数据为空，请检查 Tushare 积分（index_dailybasic 需2000积分）。")
            return

        # 优先用 pe_ttm，缺失则用 pe
        col = "pe_ttm" if "pe_ttm" in df.columns else "pe"
        pe = df[col].dropna().astype(float)
        if len(pe) == 0:
            print(f"  {col} 列全空")
            push("🌡️ 全市场温度", "## 🌡️ 全市场温度\n\nPE列数据为空。")
            return

        df = df.sort_values("trade_date")
        cur_pe = float(pe.iloc[-1])
        last_date = str(df["trade_date"].iloc[-1])

        pct_all = percentile_rank(pe, cur_pe)
        recent = pe.tail(2500)
        pct_10y = percentile_rank(recent, cur_pe)

        if pct_10y is not None:
            if pct_10y < 20:
                level = "❄️ 冰点（极度低估）"
                hint = "历史性击球区，可以贪婪。"
            elif pct_10y < 40:
                level = "🧊 偏冷（低估）"
                hint = "便宜区间，适合左侧分批。"
            elif pct_10y < 60:
                level = "🌤 合理"
                hint = "不贵不便宜，耐心等击球点。"
            elif pct_10y < 80:
                level = "🔥 偏热（高估）"
                hint = "偏贵，谨慎加仓。"
            else:
                level = "☀️ 过热（极度高估）"
                hint = "历史高位，防守为主。"
        else:
            level = "未知"
            hint = ""

        print(f"  沪深300 PE={cur_pe:.2f} 近10年分位={pct_10y}%")

        lines = [
            f"## 🌡️ 全市场温度 {now:%m-%d %H:%M}",
            "",
            f"**沪深300 PE(TTM)：{cur_pe:.2f}**",
            "",
            f"· 近10年分位：**{pct_10y}%**",
            f"· 全历史分位：{pct_all}%",
            "",
            f"**温度：{level}**",
            f"{hint}",
            "",
            "---",
            f"⏰ {now:%Y-%m-%d %H:%M} | 数据日 {last_date} | Tushare",
        ]

        push(f"🌡️ 温度 {pct_10y}%", "\n".join(lines))
        print("[DONE] 推送完成")

    except Exception as e:
        print(f"  [错误] {e}")
        push("🌡️ 全市场温度", f"## 🌡️ 全市场温度\n\n运行出错：{e}")


if __name__ == "__main__":
    main()
