#!/usr/bin/env python3
"""
大宗商品价格监控脚本 v2（2026-08-19 数据源全面更换）

旧源失效原因：生意社 100ppi.com 全站加 JS Cookie 风控（HW_CHECK 安全检查），
纯 requests 无法绕过，www/m/top/镜像子域名均返回 636 字节空壳页。

新数据源（实测可用）：
  期货类 → 新浪财经期货K线接口（碳酸锂 LC0、天然橡胶 RU0）
  现货类 → 金投网报价页（聚合MDI/钛白粉/EVA/氯化钾）+ 水泥网 CEMPI 指数
  人工维护 → 动力煤、蛋氨酸（无稳定免费数据源：
              动力煤期货 ZC 流动性死、金投网无煤炭类目；
              金投网无蛋氨酸。由对话AI人工更新 commodity_prices.json）

依赖：仅 requests（不再需要 akshare）
周期：碳酸锂+聚合MDI 每天；其余每周一
"""

import requests
import json
import os
import re
from datetime import datetime, date
from pathlib import Path

# ============================================================
# 配置
# ============================================================

COMMODITIES = {
    "碳酸锂": {
        "stocks": ["盐湖股份(000792)"],
        "level": "daily",      # 每天
        "unit": "元/吨",
        "threshold": 0.03,     # 涨跌>3%推送
        "source": "sina_kline",
        "code": "LC0",         # 新浪主力连续合约代码
    },
    "天然橡胶": {
        "stocks": ["赛轮轮胎(601058)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "sina_kline",
        "code": "RU0",
    },
    "聚合MDI": {
        "stocks": ["万华化学(600309)"],
        "level": "daily",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "jt_price",
        "slug": "juhemdi",
    },
    "钛白粉(金红石型)": {
        "stocks": ["龙佰集团(002601)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "jt_price",
        "slug": "taibaifen",
    },
    "EVA光伏料": {
        "stocks": ["福斯特(603806)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "jt_price",
        "slug": "eva",
    },
    "氯化钾": {
        "stocks": ["盐湖股份(000792)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.03,
        "source": "jt_price",
        "slug": "lvhuajia",
    },
    "水泥(CEMPI指数)": {
        "stocks": ["海螺水泥(600585)"],
        "level": "weekly",
        "unit": "点",
        "threshold": 0.02,
        "source": "ccement",
    },
    "动力煤(5500大卡)": {
        "stocks": ["海螺水泥(600585)", "兖矿能源(600188)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.02,
        "source": "manual",
        "note": "无稳定免费源(期货ZC流动性死/现货站全反爬)，人工维护",
    },
    "蛋氨酸": {
        "stocks": ["安迪苏(600299)"],
        "level": "weekly",
        "unit": "元/吨",
        "threshold": 0.03,
        "source": "manual",
        "note": "无稳定免费源，人工维护",
    },
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

DATA_FILE = Path(__file__).parent / "commodity_prices.json"


# ============================================================
# 数据获取
# ============================================================

def get_sina_kline(code):
    """新浪财经期货主力连续K线，取最新收盘价"""
    try:
        url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
               f"var%20_{code}=/InnerFuturesNewService.getDailyKLine?symbol={code}")
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = "utf-8"
        m = re.search(r"\[(.*)\]", r.text, re.S)
        if not m:
            print(f"  [sina] {code} 未匹配到K线数据")
            return None
        data = json.loads("[" + m.group(1) + "]")
        if not data:
            print(f"  [sina] {code} K线为空")
            return None
        last = data[-1]
        return {
            "price": float(last.get("c", 0)),
            "date": str(last.get("d", date.today())),
            "change_pct": None,
        }
    except Exception as e:
        print(f"  [sina] {code} 获取失败: {e}")
        return None


def get_jt_price(slug, name):
    """金投网报价：列表页取最新日报链接 → 详情页提取价格表"""
    try:
        list_url = f"https://jiage.cngold.org/{slug}/"
        r = requests.get(list_url, headers=HEADERS, timeout=15)
        r.encoding = "utf-8"
        links = re.findall(
            r'href="(https://jiage\.cngold\.org/c/\d{4}-\d{2}-\d{2}/c\d+\.html)"',
            r.text)
        if not links:
            print(f"  [金投网] {name}({slug}) 未找到日报链接")
            return None

        detail = requests.get(links[0], headers=HEADERS, timeout=15)
        detail.encoding = "utf-8"
        # 表格：产品名称 | 牌号规格 | 产品价格 | 价格单位
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", detail.text, re.S)
        for row in rows:
            cells = [re.sub(r"<[^>]+>", "", c).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
            if len(cells) >= 3:
                price_txt = cells[2].replace(",", "").strip()
                if re.fullmatch(r"\d+(\.\d+)?", price_txt):
                    return {
                        "price": float(price_txt),
                        "date": links[0].split("/c/")[1][:10] if "/c/" in links[0] else str(date.today()),
                        "change_pct": None,
                    }
        print(f"  [金投网] {name}({slug}) 详情页未匹配到价格")
    except Exception as e:
        print(f"  [金投网] {name}({slug}) 请求失败: {e}")
    return None


def get_ccement():
    """水泥网 CEMPI 全国水泥价格指数"""
    try:
        r = requests.get("https://index.ccement.com/", headers=HEADERS, timeout=15)
        r.encoding = "utf-8"
        m = re.search(
            r'<div class="item1[^"]*"[^>]*>\s*<a[^>]*>(\d+\.?\d*)\s*<i', r.text)
        if m:
            return {
                "price": float(m.group(1)),
                "date": str(date.today()),
                "change_pct": None,
            }
        print("  [水泥网] 未匹配到CEMPI指数值")
    except Exception as e:
        print(f"  [水泥网] 请求失败: {e}")
    return None


def get_commodity_price(name, cfg):
    src = cfg.get("source")
    if src == "sina_kline":
        return get_sina_kline(cfg["code"])
    if src == "jt_price":
        return get_jt_price(cfg["slug"], name)
    if src == "ccement":
        return get_ccement()
    return None


# ============================================================
# 历史数据管理
# ============================================================

def load_history():
    """读取历史数据；旧格式(带tracking键)视为废弃数据源产物，重新开始"""
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "tracking" in data:   # 旧版格式，数据源已失效，弃用
                print("检测到旧版数据格式(tracking)，重新初始化。")
                return {}
            return data
    except Exception as e:
        print(f"历史数据读取失败，重新初始化: {e}")
    return {}


def save_history(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 通知推送
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
    if cfg.get("level") == "daily":
        return True
    return datetime.now().weekday() == 0  # weekly 只在周一


def main():
    print(f"=== 大宗商品价格监控 v2 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"星期: {['一','二','三','四','五','六','日'][datetime.now().weekday()]}")

    history = load_history()
    alerts = []
    fetch_fails = []
    all_data = {}

    for name, cfg in COMMODITIES.items():
        unit = cfg["unit"]
        stocks_str = ", ".join(cfg["stocks"])

        # ---- 人工维护类 ----
        if cfg.get("source") == "manual":
            old = history.get(name, {})
            if old.get("price"):
                record = dict(old)
                record["stocks"] = stocks_str
                record["unit"] = unit
                record["manual"] = True
                all_data[name] = record
                print(f"[{name}] 人工维护: {old['price']:,.0f} {unit} ({old.get('date','')})")
            else:
                all_data[name] = {
                    "price": None, "date": "", "unit": unit,
                    "stocks": stocks_str, "manual": True,
                }
                print(f"[{name}] 人工维护: 尚未录入价格")
            continue

        # ---- 非检查日 ----
        if not should_check_today(cfg):
            all_data[name] = history.get(name, {})
            continue

        # ---- 自动抓取 ----
        print(f"\n[{name}] 获取中...")
        result = get_commodity_price(name, cfg)
        if result is None or not result.get("price"):
            print(f"  ❌ 获取失败，沿用上次数据")
            fetch_fails.append(name)
            all_data[name] = history.get(name, {})
            continue

        new_price = result["price"]
        old_data = history.get(name, {})
        old_price = old_data.get("price")

        record = {
            "price": new_price,
            "date": result.get("date") or str(date.today()),
            "unit": unit,
            "stocks": stocks_str,
        }
        all_data[name] = record

        print(f"  ✅ {new_price:,.0f} {unit} ({record['date']})")

        if old_price and old_price > 0:
            change_pct = (new_price - old_price) / old_price
            record["change_pct"] = round(change_pct, 4)
            direction = "↑" if change_pct > 0 else "↓" if change_pct < 0 else "→"
            print(f"     上次: {old_price:,.0f}  |  变动: {direction} {abs(change_pct)*100:.1f}%")
            if abs(change_pct) >= cfg["threshold"]:
                alerts.append({
                    "name": name, "price": new_price, "old_price": old_price,
                    "change_pct": change_pct, "stocks": cfg["stocks"],
                    "unit": unit,
                })

    save_history(all_data)

    # ============================================================
    # 生成推送内容
    # ============================================================
    today_weekday = datetime.now().weekday()
    is_weekly_day = today_weekday == 0

    if not alerts and not is_weekly_day:
        print("\n今日非周报日，无告警，不推送。")
        return

    content_parts = []

    # 告警部分
    if alerts:
        content_parts.append(f"## ⚠️ 商品价格告警 ({len(alerts)}项)")
        content_parts.append("")
        content_parts.append("| 商品 | 现价 | 变动 | 影响股票 |")
        content_parts.append("|------|------|------|----------|")
        for a in alerts:
            direction = "📈" if a["change_pct"] > 0 else "📉"
            content_parts.append(
                f"| {a['name']} | {a['price']:,.0f} {a['unit']} | "
                f"{direction} {a['change_pct']*100:+.1f}% | "
                f"{', '.join(a['stocks'])} |")
        content_parts.append("")

    # 周报部分（周一）
    if is_weekly_day:
        content_parts.append("## 📋 周度商品价格总览")
        content_parts.append("")
        content_parts.append("| 商品 | 现价 | 影响股票 |")
        content_parts.append("|------|------|----------|")
        for name, cfg in COMMODITIES.items():
            data = all_data.get(name, {})
            price = data.get("price")
            if data.get("manual"):
                tag = " ✍️人工维护"
                price_str = f"{price:,.0f} {cfg['unit']}" if price else "未录入"
            else:
                tag = ""
                price_str = f"{price:,.0f} {cfg['unit']}" if price else "获取失败"
            content_parts.append(
                f"| {name}{tag} | {price_str} | {data.get('stocks', ', '.join(cfg['stocks']))} |")
        content_parts.append("")

    if fetch_fails:
        content_parts.append(f"⚠️ 本次获取失败: {'、'.join(fetch_fails)}（沿用上次数据）")
        content_parts.append("")

    content_parts.append("---")
    content_parts.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
                         f"监控9商品→8框架股 | 下次周报: 下周一")

    title = "⚡ 商品告警" if alerts else "📋 商品周报"
    content = "\n".join(content_parts)

    print(f"\n{'='*50}")
    print(content[:800])
    print(f"{'='*50}")

    pushplus_send(title, content)
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
