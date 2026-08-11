"""
利润缓存 v3
新浪财报页 → HTML解析 → 营收/利润增速
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


def get_profit_sina(code):
    """新浪财报摘要页 → 近两年年报利润增速"""
    try:
        url = (
            f"https://money.finance.sina.com.cn/corp/go.php/"
            f"vFD_FinanceSummary/stockid/{code}/displaytype/4.phtml"
        )
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "gb2312"

        text = r.text

        # 财务指标表: td 里是年份-12-31 紧跟数字
        # <tr><td>2025-12-31</td><td>2024-12-31</td><td>2023-12-31</td>...</tr>
        # 找包含"净利润"的行 后面跟数据行

        # 简化：找包含 2025-12-31 和 2024-12-31 且包含净利润的行
        # 或者直接用正则找 营收/净利行

        # 模式：先找表头年份
        year_row = re.search(
            r'(\d{4})-12-31.*?(\d{4})-12-31.*?(\d{4})-12-31', text
        )
        if not year_row:
            return None

        y1, y2, y3 = year_row.group(1), year_row.group(2), year_row.group(3)

        # 找"净利润"后面紧跟的三列数字
        profit_row = re.search(
            r'净利润</a>.*?</tr>.*?<tr[^>]*>(.*?)</tr>',
            text, re.DOTALL
        )
        if not profit_row:
            # 换种方式
            profit_row = re.search(
                r'归属于母公司所有者的净利润.*?</tr>.*?<tr[^>]*>(.*?)</tr>',
                text, re.DOTALL
            )

        if not profit_row:
            return None

        cells = re.findall(r'<td[^>]*>([-\d.,]+)</td>', profit_row.group(1))
        if len(cells) < 2:
            return None

        cur_p = float(cells[0].replace(",", "")) if cells[0] != "--" else None
        prev_p = float(cells[1].replace(",", "")) if cells[1] != "--" else None

        profit_yoy = None
        if cur_p and prev_p and prev_p != 0:
            profit_yoy = round((cur_p - prev_p) / abs(prev_p) * 100, 1)

        # 营收
        rev_row = re.search(
            r'营业总收入.*?</tr>.*?<tr[^>]*>(.*?)</tr>',
            text, re.DOTALL
        )
        rev_yoy = None
        if rev_row:
            r_cells = re.findall(r'<td[^>]*>([-\d.,]+)</td>', rev_row.group(1))
            if len(r_cells) >= 2:
                cur_r = float(r_cells[0].replace(",", "")) if r_cells[0] != "--" else None
                prev_r = float(r_cells[1].replace(",", "")) if r_cells[1] != "--" else None
                if cur_r and prev_r and prev_r != 0:
                    rev_yoy = round((cur_r - prev_r) / abs(prev_r) * 100, 1)

        return {
            "profit_yoy": profit_yoy,
            "rev_yoy": rev_yoy,
            "report_date": f"{y1}-12-31",
            "source": "sina",
        }
    except Exception as e:
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
    print(f"[START] 利润缓存 v3 {now:%Y-%m-%d}")

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
    for code in sorted(codes):
        if code in cache and cache[code].get("profit_yoy") is not None:
            hit += 1
            continue

        d = get_profit_sina(code)
        if d and d.get("profit_yoy") is not None:
            cache[code] = d
            hit += 1
            print(f"  {code} ✅ profit_yoy={d['profit_yoy']}%")
        else:
            cache[code] = {"profit_yoy": None, "rev_yoy": None, "report_date": "?", "source": "sina"}
            miss += 1
            print(f"  {code} ❌")
        time.sleep(0.5)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    total = len(codes)
    ok = sum(1 for c in codes if cache.get(c, {}).get("profit_yoy") is not None)
    lines = [
        f"利润缓存 {now:%m}.{now:%d}",
        f"扫描{total}只 | 成功{ok}只 | 新增{hit}只",
    ]

    still_miss = [c for c in sorted(codes) if cache.get(c, {}).get("profit_yoy") is None]
    if still_miss:
        names = []
        for c in still_miss:
            t = trigger.get(c, {})
            names.append(t.get("name", c) if isinstance(t, dict) else c)
        lines.append("")
        lines.append(f"⚠️ 仍缺失 {len(still_miss)}只 {', '.join(names[:8])}")

    lines.append("")
    lines.append("> 新浪财报HTML | 年报同比 | 需commit持久化")

    push(f"利润缓存 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
