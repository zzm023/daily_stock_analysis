#!/usr/bin/env python3
"""
全市场估值温度 v1.0（任务⑩）
功能：沪深300 PE(TTM) 历史分位 → 大盘温度计
数据源：akshare stock_a_pe（乐咕乐股，沪深300历史PE）
运行：收盘后 17:00
"""

import os
import requests
from datetime import datetime, timezone, timedelta

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
    """计算 value 在 series 中的历史分位（0-100）"""
    if len(series) == 0:
        return None
    below = (series <= value).sum()
    return round(below / len(series) * 100, 1)


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[START] 全市场温度 {now:%m-%d %H:%M}")

    try:
        import akshare as ak
        df = ak.stock_a_pe(market="000300.XSHG")
        if df is None or df.empty:
            print("  沪深300 PE 数据为空")
            push("🌡️ 全市场温度", "## 🌡️ 全市场温度\n\n数据为空，请检查数据源。")
            return

        # 取加权PE(TTM)序列
        pe = df["averagePETTM"].dropna()
        if len(pe) == 0:
            print("  averagePETTM 列缺失")
            push("🌡️ 全市场温度", "## 🌡️ 全市场温度\n\nPE数据列缺失。")
            return

        cur_pe = float(pe.iloc[-1])
        last_date = str(df["date"].iloc[-1])[:10]

        # 历史分位（用近10年 + 全历史）
        pct_all = percentile_rank(pe, cur_pe)
        recent = pe.tail(2500)   # 约10年交易日
        pct_10y = percentile_rank(recent, cur_pe)

        # 温度分档
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

        print(f"  沪深300 PE(TTM)={cur_pe:.2f} 分位={pct_10y}%")

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
            f"⏰ {now:%Y-%m-%d %H:%M} | 数据日 {last_date} | 乐咕乐股",
        ]

        push(f"🌡️ 温度 {pct_10y}% {level.split(' ')[1]}", "\n".join(lines))
        print("[DONE] 推送完成")

    except ImportError:
        print("  [错误] 未安装 akshare")
        push("🌡️ 全市场温度", "## 🌡️ 全市场温度\n\n未安装 akshare，请在 yml 加依赖。")
    except Exception as e:
        print(f"  [错误] {e}")
        push("🌡️ 全市场温度", f"## 🌡️ 全市场温度\n\n运行出错：{e}")


if __name__ == "__main__":
    main()
