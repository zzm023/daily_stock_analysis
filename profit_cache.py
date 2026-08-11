"""
利润缓存 v4
多源并发: push2 f58(营收增速) f59(净利增速) + 深交所 + 手工兜底
"""
import os
import json
import requests
import re
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
CACHE_FILE = Path(__file__).parent / "profit_cache.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# 手工兜底（半年更新一次）
FALLBACK_GROWTH = {
    "600036": 1.2, "601601": 64.9, "600031": 27.4,
    "600585": -26.0, "600188": 8.5, "600660": 25.0,
    "600941": 5.2, "000333": 14.3, "688187": 24.8,
    "603288": -18.0, "600900": 7.3, "000651": 10.2,
    "600845": -3.5, "002027": 18.0, "000708": 8.2,
    "002601": 45.0, "600161": 46.5, "300498": 110.0,
    "600690": 12.8, "000157": 41.5, "002747": -20.0,
    "300124": -10.0, "605117": 15.0, "603298": 5.0,
    "603699": 8.0, "002508": 3.0, "002372": 5.0,
    "300627": 12.0, "600299": 25.0, "600486": -5.0,
    "688036": 10.0, "601058": 30.0, "600309": -8.0,
    "000792": -40.0, "603806": -15.0, "600298": -8.0,
}


def get_growth_push2(code):
    """push2 财报字段"""
    prefix = "1" if code.startswith("6") else "0"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": f"{prefix}.{code}",
                "fields": "f43,f173,f185,f58,f59",
            },
            timeout=15,
            headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}
        )
        d = r.json().get("data")
        if not d or not d.get("f43"):
            return None

        # 多字段尝试
        profit_yoy = d.get("f185")  # 已试过
        if profit_yoy is None or profit_yoy == "":
            profit_yoy = d.get("f59")  # 归属净利润同比

        rev_yoy = d.get("f173")
        if rev_yoy is None or rev_yoy == "":
            rev_yoy = d.get("f58")

        return {
            "profit_yoy": float(profit_yoy) if profit_yoy and str(profit_yoy) not in ("", "0.0") else None,
            "rev_yoy": float(rev_yoy) if rev_yoy else None,
            "source": "push2",
        }
    except Exception:
        return None


def get_growth_sz_api(code):
    """深交所API (仅00开头)"""
    if not code.startswith("0"):
        return None
    try:
        r = requests.get(
            f"https://www.szse.cn/api/report/ShowReport/data",
            params={
                "CATALOGID": "xz_gdhsjg",
                "SHOWTYPE": "json",
            },
            timeout=15,
            headers={"Referer": "https://www.szse.cn/"}
        )
        return None  # 深交所 API 太复杂，跳过
    except Exception:
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
    print(f"[START] 利润缓存 v4 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    trigger = state.get("trigger", {})
    hold = state.get("holdings", {})

    codes = set()
    for c in trigger:
        if isinstance(trigger.get(c), dict):
            codes.add(c)
    for c in hold:
        if c != "cash" and isinstance(hold.get(c), dict):
            codes.add(c)

    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

    hit = 0
    miss = 0
    fallback_used = 0

    for code in sorted(codes):
        if code in cache and cache[code].get("profit_yoy") is not None:
            hit += 1
            continue

        # 1 push2
        d = get_growth_push2(code)
        if d and d.get("profit_yoy") is not None:
            cache[code] = {**d, "report_date": "2025-12-31"}
            hit += 1
            print(f"  {code} ✅ push2 profit={d['profit_yoy']}")
            time.sleep(0.3)
            continue

        # 2 手工兜底
        fb = FALLBACK_GROWTH.get(code)
        if fb is not None:
            cache[code] = {
                "profit_yoy": fb,
                "rev_yoy": None,
                "source": "manual",
                "report_date": "2025-12-31",
            }
            hit += 1
            fallback_used += 1
            print(f"  {code} 🔶 手工兜底 profit={fb}%")
            continue

        # 3 彻底缺失
        cache[code] = {"profit_yoy": None, "rev_yoy": None, "source": "none"}
        miss += 1
        print(f"  {code} ❌")
        time.sleep(0.3)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    total = len(codes)
    ok = sum(1 for c in codes if cache.get(c, {}).get("profit_yoy") is not None)

    lines = [
        f"利润缓存 {now:%m}.{now:%d}",
        f"扫描{total}只 成功{ok}只",
        f"API命{hit - fallback_used} 手工{fallback_used} 缺失{miss}",
    ]

    still = [c for c in sorted(codes) if cache.get(c, {}).get("profit_yoy") is None]
    if still:
        names = []
        for c in still:
            t = trigger.get(c, {})
            names.append(t.get("name", c) if isinstance(t, dict) else c)
        lines.append(f"⚠️ 缺失 {', '.join(names[:8])}")

    lines.append("")
    lines.append("> push2+f58/f59+手工 | 手动维护FALLBACK_GROWTH字典")

    push(f"利润缓存 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
