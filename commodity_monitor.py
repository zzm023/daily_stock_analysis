#!/usr/bin/env python3
"""
大宗商品价格监控 v1.3
期货品种：碳酸锂(LC)、天然橡胶(RU) 每天/每周
现货品种：生意社反爬，暂时降级（SPOT_ENABLE=False）

数据源：akshare futures_main_sina（期货主力）
运行：每日 08:00
"""

import requests
import json
import os
from datetime import datetime, date
from pathlib import Path

# ============================================================
# 配置
# ============================================================

SPOT_ENABLE = False   # 生意社现货数据源维护中，暂时关闭

# 期货品种（akshare 可用）
COMMODITIES = {
    "碳酸锂": {
        "stocks": ["盐湖股份(000792)"],
        "level": "daily",
        "unit": "元/吨",
        "threshold": 0.03,
        "source": "futures",
        "code": "LC",
    },
    "天然橡胶": {
        "stocks": ["赛轮轮胎(601058)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "futures",
        "code": "RU",
    },
}

# 现货品种（生意社反爬，暂停；保留配置方便后续恢复）
SPOT_COMMODITIES = {
    "聚合MDI": {"stocks": ["万华化学(600309)"], "level": "daily", "unit": "元/吨", "threshold": 0.02, "ppid": "264"},
    "钛白粉(金红石型)": {"stocks": ["龙佰集团(002601)"], "level": "weekly", "unit": "元/吨", "threshold": 0.02, "ppid": "764"},
    "蛋氨酸": {"stocks": ["安迪苏(600299)"], "level": "weekly", "unit": "元/公斤", "threshold": 0.03, "ppid": "843"},
    "PO42.5水泥": {"stocks": ["海螺水泥(600585)"], "level": "weekly", "unit": "元/吨", "threshold": 0.02, "ppid": "308"},
    "动力煤(5500大卡)": {"stocks": ["海螺水泥(600585)", "兖矿能源(600188)"], "level": "weekly", "unit": "元/吨", "threshold": 0.02, "ppid": "345"},
    "氯化钾": {"stocks": ["盐湖股份(000792)"], "level": "weekly", "unit": "元/吨", "threshold": 0.03, "ppid": "389"},
    "EVA光伏料": {"stocks": ["福斯特(603806)"], "level": "weekly", "unit": "元/吨", "threshold": 0.02, "ppid": "1139"},
}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")
DATA_FILE = Path(__file__).parent / "commodity_prices.json"


# ============================================================
# 数据获取
# ============================================================

def get_futures_price(code):
    try:
        import akshare as ak
        df = ak.futures_main_sina(symbol=code)
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            return {
                "price": float(latest["收盘价"]),
                "date": str(latest["日期"]) if "日期" in df.columns else str(date.today()),
                "change_pct": float(latest.get("涨跌幅", 0)),
            }
    except Exception as e:
        print(f"  [akshare期货] {code} 获取失败: {e}")
    return None


# ============================================================
# 历史数据管理
# ============================================================

def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 推送
# ============================================================

def pushplus_send(title, content):
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


# ============================================================
# 主逻辑
# ============================================================

def should_check_today(cfg):
    if cfg["level"] == "daily":
        return True
    return datetime.now().weekday() == 0


def main():
    now = datetime.now()
    print(f"[START] 大宗商品 {now:%m-%d %H:%M} 星期{['一','二','三','四','五','六','日'][now.weekday()]}")

    history = load_history()
    alerts = []
    weekly_items = []
    all_data = {}
    ok_count = 0
    fail_count = 0

    for name, cfg in COMMODITIES.items():
        if not should_check_today(cfg):
            all_data[name] = history.get(name, {})
            continue

        print(f"[{name}] 获取中...")
        result = get_futures_price(cfg["code"])

        if result is None:
            print(f"  获取失败，跳过")
            all_data[name] = history.get(name, {})
            fail_count += 1
            continue

        new_price = result["price"]
        old_data = history.get(name, {})
        old_price = old_data.get("price")

        record = {
            "name": name,
            "price": new_price,
            "date": result["date"],
            "unit": cfg["unit"],
            "stocks": ", ".join(cfg["stocks"]),
        }
        all_data[name] = record
        ok_count += 1

        print(f"  {new_price:,.0f} {cfg['unit']}")

        if old_price and old_price > 0:
            change_pct = (new_price - old_price) / old_price
            record["change_pct"] = round(change_pct, 4)
            direction = "↑" if change_pct > 0 else "↓" if change_pct < 0 else "→"
            print(f"     上次 {old_price:,.0f} → {direction} {abs(change_pct)*100:.1f}%")

            if abs(change_pct) >= cfg["threshold"]:
                alerts.append({
                    "name": name,
                    "price": new_price,
                    "old_price": old_price,
                    "change_pct": change_pct,
                    "stocks": cfg["stocks"],
                    "unit": cfg["unit"],
                })

        if cfg["level"] == "weekly" and now.weekday() == 0:
            weekly_items.append(record)

    save_history(all_data)

    if not alerts and not weekly_items:
        print(f"无告警无周报。成功{ok_count} 失败{fail_count}。")
        return

    lines = [f"## 📊 大宗商品 {now:%m-%d %H:%M}", f"成功{ok_count}项 · 失败{fail_count}项", ""]

    if alerts:
        lines.append(f"**🔴 商品价格告警（{len(alerts)}项）**")
        lines.append("")
        for a in alerts:
            direction = "📈" if a["change_pct"] > 0 else "📉"
            lines.append(f"· {a['name']} 现{a['price']:,.0f}{a['unit']} {direction}{a['change_pct']*100:+.1f}% 影响{', '.join(a['stocks'])}")
            lines.append("")

    if weekly_items and now.weekday() == 0:
        lines.append("**📋 周度商品快照**")
        lines.append("")
        for item in weekly_items:
            lines.append(f"· {item['name']} 现{item['price']:,.0f}{item['unit']} 影响{item['stocks']}")
            lines.append("")

    lines.append("---")
    lines.append(f"⏰ {now:%Y-%m-%d %H:%M} | 期货2品种 | 现货7品种维护中")

    title = "⚡ 商品告警" if alerts else "📋 商品周报"
    pushplus_send(title, "\n".join(lines))
    print("[DONE] 推送完成")


if __name__ == "__main__":
    main()
