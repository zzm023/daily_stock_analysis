#!/usr/bin/env python3
"""大股东增减持+质押+解禁周报：标题+正文双重扫描
"""
import requests
import re
import os
from datetime import datetime, timedelta

STOCKS = [
    ("600036","招商银行"),("601601","中国太保"),("600018","上港集团"),("601816","京沪高铁"),
    ("600900","长江电力"),("600941","中国移动"),("600406","国电南瑞"),("600598","北大荒"),
    ("603568","伟明环保"),("600007","中国国贸"),("000429","粤高速A"),("000895","双汇发展"),
    ("000848","承德露露"),("000157","中联重科"),("600585","海螺水泥"),("000792","盐湖股份"),
    ("600188","兖矿能源"),("002601","龙佰集团"),("600299","安迪苏"),("300498","温氏股份"),
    ("000651","格力电器"),("600066","宇通客车"),("000333","美的集团"),("600690","海尔智家"),
    ("600031","三一重工"),("600309","万华化学"),("600660","福耀玻璃"),("600761","安徽合力"),
    ("600486","扬农化工"),("601058","赛轮轮胎"),("603806","福斯特"),("000708","中信特钢"),
    ("002027","分众传媒"),("000538","云南白药"),("603605","珀莱雅"),("605098","行动教育"),
    ("600298","安琪酵母"),("300628","亿联网络"),("002508","老板电器"),("002032","苏泊尔"),
    ("002884","凌霄泵业"),("002318","久立特材"),("603855","华荣股份"),("603288","海天味业"),
    ("603508","思维列控"),("600161","天坛生物"),("300832","新产业"),("688187","时代电气"),
    ("300124","汇川技术"),("002837","英维克"),("300627","华测导航"),("002410","广联达"),
]

KEYWORDS = ["增持", "减持", "权益变动", "质押", "解禁", "限售"]
ANNO_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
CONTENT_URL = "https://np-cnotice-stock.eastmoney.com/api/content/ann"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_announcements(codes_str, page=1):
    params = {
        "sr": -1, "page_size": 50, "page_index": page, "ann_type": "A",
        "client_source": "web", "stock_list": codes_str, "f_node": 0, "s_node": 0,
    }
    r = requests.get(ANNO_URL, params=params, headers=HEADERS, timeout=15)
    return r.json()


def get_pdf_url(art_code):
    try:
        r = requests.get(CONTENT_URL, params={"art_code": art_code, "client_source": "web", "page_index": 1},
                         headers=HEADERS, timeout=15)
        data = (r.json().get("data") or {})
        for key in ("attach_list", "attach_list_ch"):
            lst = data.get(key) or []
            if lst and lst[0].get("attach_url"):
                return lst[0]["attach_url"]
    except Exception:
        pass
    return ""


def parse_pdf(url):
    if not url.startswith("http"):
        url = "https://static.cninfo.com.cn/" + url
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(r.content))
        parts = []
        for page in reader.pages[:5]:
            parts.append(page.extract_text() or "")
        return re.sub(r"\s+", " ", " ".join(parts))
    except Exception as e:
        print(f"  PDF解析失败: {e}")
        return ""


def fetch_text(art_code):
    """返回公告全文文字（PDF）"""
    url = get_pdf_url(art_code) if art_code else ""
    if url:
        return parse_pdf(url)
    return ""


def extract_summary(text):
    if not text:
        return "正文未获取"
    sentences = [s.strip() for s in re.split(r"[。；;]", text) if s.strip()]
    picks = []

    # 解禁类
    for s in sentences:
        if "解禁" not in s and "解除限售" not in s and "限售股" not in s:
            continue
        m_qty = re.search(r"(\d[\d,\.]*)\s*(亿|万)?股", s)
        m_pct = re.search(r"占(?:公司)?总股本(?:比例)?\s*(\d+(?:\.\d+)?)\s*%", s)
        if m_qty or m_pct:
            parts = []
            if m_qty:
                parts.append(f"{m_qty.group(1)}{m_qty.group(2) or ''}股")
            if m_pct:
                parts.append(f"占总股本{m_pct.group(1)}%")
            picks.append(f"解禁{'、'.join(parts)}")

    # 质押类（排除"前/后持股"表格句）
    for s in sentences:
        if "质押" not in s:
            continue
        if re.search(r"(质押|持有)(前|后)|累计质押股份(数量|总数)", s) and "本次" not in s and "解除" not in s:
            if "本次" not in s:
                continue
        m_qty = re.search(r"(\d[\d,\.]*)\s*(亿|万)?股", s)
        m_own = re.search(r"占其(?:所持|持有)?股份(?:比例)?\s*(\d+(?:\.\d+)?)\s*%", s)
        m_total = re.search(r"占(?:公司)?总股本(?:比例)?\s*(\d+(?:\.\d+)?)\s*%", s)
        if m_qty or m_own or m_total:
            parts = []
            kind = "解除质押" if "解除质押" in s else "质押"
            if m_qty:
                parts.append(f"{m_qty.group(1)}{m_qty.group(2) or ''}股")
            if m_own:
                parts.append(f"占其持{m_own.group(1)}%")
            if m_total:
                parts.append(f"占总股本{m_total.group(1)}%")
            picks.append(f"{kind}{'、'.join(parts)}")

    # 增减持类（优先"本次/拟/计划/累计"，排除表格句）
    zd = []
    for s in sentences:
        if ("减持" not in s and "增持" not in s) or "质押" in s:
            continue
        m_qty = re.search(r"(不超过\s*)?(\d[\d,\.]*)\s*(亿|万)?股", s)
        m_pct = re.search(r"占[^%]{0,15}?(\d+(?:\.\d+)?)\s*%", s)
        if not (m_qty or m_pct):
            continue
        if re.search(r"(增持|减持)(前|后)持股|变动(前|后)|期末持股", s):
            continue
        score = sum(1 for kw in ["本次", "拟", "计划", "累计", "已完成"] if kw in s)
        qty = f"{m_qty.group(2)}{m_qty.group(3) or ''}股" if m_qty else ""
        pct = f"{m_pct.group(1)}%" if m_pct else ""
        kind = "减持" if "减持" in s else "增持"
        zd.append((score, f"{kind}{qty}{('/' + pct) if pct else ''}"))
    zd.sort(key=lambda x: -x[0])
    picks.extend(p for _, p in zd[:3])

    if picks:
        seen, out = set(), []
        for p in picks:
            if p not in seen:
                seen.add(p); out.append(p)
        return "；".join(out[:4])

    for s in sentences:
        if any(k in s for k in KEYWORDS):
            return s[:60] + ("…" if len(s) > 60 else "")
    return "未提取到数量信息"


def push(title, content):
    token = os.getenv("PUSHPLUS_TOKEN")
    topic = os.getenv("PUSHPLUS_TOPIC")
    if not token:
        print("[WARN] 无TOKEN"); return
    payload = {"token": token, "title": title, "content": content, "template": "markdown"}
    if topic: payload["topic"] = topic
    r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
    print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")


def main():
    import time
    now = datetime.now()
    since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"[START] 标题+正文扫描 {now:%Y-%m-%d %H:%M}")

    # 1. 收集7天内全部公告
    anns = []
    codes = [c for c, _ in STOCKS]
    for i in range(0, len(codes), 50):
        batch = ",".join(codes[i:i+50])
        for page in (1, 2):
            for attempt in range(3):
                try:
                    j = fetch_announcements(batch, page)
                    lst = (j.get("data") or {}).get("list") or []
                    new = [a for a in lst if (a.get("notice_date") or "")[:10] >= since]
                    anns.extend(new)
                    print(f"  批次{i//50+1} 第{page}页: 窗口内 {len(new)}条")
                    if len(lst) < 50 or not new:
                        break  # 没有更多了
                    break
                except Exception as e:
                    if attempt < 2:
                        print(f"  重试..."); time.sleep(4*(attempt+1))
                    else:
                        print(f"  失败: {e}")
        time.sleep(0.3)

    # 去重
    seen, anns2 = set(), []
    for a in anns:
        if a.get("art_code") not in seen:
            seen.add(a.get("art_code")); anns2.append(a)
    print(f"  7天内公告共 {len(anns2)} 条")

    # 2. 标题命中直接记；标题没命中拉PDF扫正文
    hits = []
    for idx, a in enumerate(anns2):
        date = (a.get("notice_date") or "")[:10]
        title = a.get("title", "")
        cds = (a.get("codes") or [{}])[0]
        name = cds.get("short_name", "") or (title.split(":")[0] if ":" in title else "")
        code = cds.get("stock_code", "")
        art_code = a.get("art_code", "")
        title_hit = any(k in title for k in KEYWORDS)

        summary = None
        if title_hit:
            text = fetch_text(art_code)
            summary = extract_summary(text)
            print(f"  [标题] {name} {date} → {summary}")
        else:
            text = fetch_text(art_code)
            if text and any(k in text for k in KEYWORDS):
                summary = extract_summary(text)
                print(f"  [正文] {name} {date} → {summary}")
            else:
                summary = None
        if summary:
            hits.append({"name": name, "code": code, "date": date,
                         "title": title, "summary": summary, "tag": "标题" if title_hit else "正文"})
        if (idx + 1) % 20 == 0:
            print(f"  进度 {idx+1}/{len(anns2)}")
        time.sleep(0.2)

    # 3. 推送
    lines = [f"## 📢 增减持+质押+解禁 — {now:%Y.%m.%d}", "",
             f"> 近7天｜ 标题+正文双扫 ｜ 命中 {len(hits)} 条", ""]
    if hits:
        for h in hits:
            lines.append(f"### {h['name']}({h['code']}) ｜ {h['date']} ｜ [{h['tag']}]")
            lines.append(f"- 摘要：{h['summary']}")
            lines.append("")
    else:
        lines.append("本周无相关公告 ✅")

    push(f"📢 增减持+质押+解禁周报 {now:%Y.%m.%d}", "\n".join(lines))
    print(f"[DONE] 命中 {len(hits)} 条")


if __name__ == "__main__":
    main()
