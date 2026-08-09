#!/usr/bin/env python3
"""
增减持+质押+解禁监控 v2
联动触发清单：只监控已触发/接近的股票
数据源：东财公告API ｜ 写事件到 framework_state.json ｜ 自动提交
每周一 08:30 CST
"""
import requests
import os
import re
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"

ALL_STOCKS = {
    "600036":"招商银行","601601":"中国太保","600018":"上港集团","601816":"京沪高铁",
    "600900":"长江电力","600941":"中国移动","600406":"国电南瑞","600598":"北大荒",
    "603568":"伟明环保","600007":"中国国贸","000429":"粤高速A","000157":"中联重科",
    "600585":"海螺水泥","000792":"盐湖股份","600188":"兖矿能源","002601":"龙佰集团",
    "600299":"安迪苏","300498":"温氏股份","000651":"格力电器","600066":"宇通客车",
    "000333":"美的集团","600690":"海尔智家","600031":"三一重工","600309":"万华化学",
    "600660":"福耀玻璃","600761":"安徽合力","600486":"扬农化工","601058":"赛轮轮胎",
    "603806":"福斯特","000708":"中信特钢","002027":"分众传媒","000538":"云南白药",
    "603605":"珀莱雅","605098":"行动教育","600298":"安琪酵母","300628":"亿联网络",
    "002508":"老板电器","002032":"苏泊尔","002884":"凌霄泵业","002318":"久立特材",
    "603855":"华荣股份","603288":"海天味业","603508":"思维列控","600161":"天坛生物",
    "300832":"新产业","688187":"时代电气","300124":"汇川技术","002837":"英维克",
    "300627":"华测导航","002410":"广联达",
}

KEYWORDS = [
    "减持", "增持", "质押", "解禁", "解除质押", "补充质押",
    "大宗交易", "协议转让", "权益变动", "简式权益变动",
    "要约收购", "集中竞价", "可交债", "EB换股",
]

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trigger": {}, "holdings": {}, "events": []}


def save_state(s):
    s["meta"] = s.get("meta", {})
    s["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def fetch_anns(code):
    now = datetime.now()
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    all_rows = []
    for page in range(1, 6):
        try:
            r = requests.get(
                "https://np-anotice-stock.eastmoney.com/api/security/ann",
                params={
                    "sr": "-1", "page_size": "50", "page_index": str(page),
                    "ann_type": "A", "client_source": "web",
                    "stock_list": code, "f_node": "0", "s_node": "0",
                    "begin_time": start, "end_time": end,
                }, timeout=15
            )
            d = r.json()
            raw = d.get("data", [])
            if isinstance(raw, dict):
                data = raw.get("list", [])
            elif isinstance(raw, list):
                data = raw
            else:
                break
            if not data:
                break
            for item in data:
                if isinstance(item, dict):
                    all_rows.append(item)
            if len(data) < 50:
                break
        except Exception as e:
            print(f"  {code} 第{page}页失败: {e}")
            break
    return all_rows


def fetch_text(art_code):
    try:
        r = requests.get(
            "https://np-anotice-stock.eastmoney.com/api/security/ann/detail",
            params={"art_code": str(art_code)},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15
        )
        return r.text or ""
    except Exception:
        return ""


def clean(text):
    return re.sub(r'<[^>]+>', ' ', str(text).replace("&nbsp;", " ")).replace("\r", "\n")


def extract_summary(text, title=""):
    raw = clean(text)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n|\n{2,}', raw) if len(p.strip()) > 20]

    t = ""
    if any(k in title for k in ["减持","拟减持","减持计划","集中竞价"]): t = "减持"
    if any(k in title for k in ["增持","拟增持","增持计划"]): t = "增持"
    if any(k in title for k in ["解除质押"]): t = "解除质押"
    elif any(k in title for k in ["质押","补充质押"]): t = "质押"
    if any(k in title for k in ["解禁","上市流通"]): t = "解禁"

    kw_list = [k for k in [t, "减持", "增持", "质押", "解禁", "权益变动", "转让"] if k]
    relevant = [p for p in paragraphs if any(k in p for k in kw_list)]

    for p in relevant[:5]:
        pcts = re.findall(r'(\d+\.?\d{0,2})\s*%', p)
        shares = re.findall(r'([\d,]+\.?\d{0,2})\s*[万万千]?股', p)
        if pcts or shares:
            parts = []
            if shares:
                parts.append(f"{shares[0].replace(',','')}股")
            if pcts:
                parts.append(f"{pcts[0]}%")
            return f"{(t or '权益变动')} {'/'.join(parts)}"

    return t or None


def push(title, content):
    if not PUSHPLUS_TOKEN:
        print("[WARN] 无TOKEN"); return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=30)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def git_commit_state():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", "framework_state.json"], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "[auto] 更新增减持事件"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("[GIT] framework_state.json 已提交")
    except Exception as e:
        print(f"[GIT] 提交失败: {e}")


def main():
    now = datetime.now()
    print(f"[START] 增减持监控 v2 {now:%Y-%m-%d %H:%M}")

    state = load_state()
    trigger = state.get("trigger", {})

    active_codes = {c for c, v in trigger.items() if v.get("status") in ("已触发","接近")}
    print(f"  触发清单: {len(active_codes)} 只")

    hits = []
    for code in active_codes:
        name = ALL_STOCKS.get(code, code)
        anns = fetch_anns(code)
        if not anns:
            continue
        matched = 0
        for a in anns:
            title = str(a.get("notice_title", ""))
            if any(k in title for k in ["激励","授予","回购注销","回购实施","理财产品","闲置资金"]):
                continue
            if not any(k in title for k in KEYWORDS):
                continue
            art_code = a.get("art_code", "")
            notice_date = str(a.get("notice_date", ""))[:10]
            text = fetch_text(art_code)
            if not text:
                continue
            summary = extract_summary(text, title)
            if summary:
                if "增持" in summary or "增持" in title:
                    impact = "利好"
                elif "减持" in summary:
                    impact = "利空" if any(x in summary for x in ["5%","大股东","实控人"]) else "轻微"
                else:
                    impact = "关注"

                print(f"  🔥 {name} {notice_date} → {summary} [{impact}]")
                hits.append({"name": name, "code": code, "date": notice_date,
                             "title": title, "summary": summary, "impact": impact})
                matched += 1
        print(f"  {name}: {len(anns)}条/命中{matched}")

    events = []
    for h in hits:
        events.append({
            "type": "增减持",
            "code": h["code"],
            "name": h["name"],
            "date": h["date"],
            "title": h["title"],
            "summary": h["summary"],
            "impact": h["impact"]
        })
    state["events"] = events
    save_state(state)

    if not hits:
        print("[INFO] 近7天无触发清单相关公告")
        push(f"📢 增减持 {now:%Y.%m.%d}", f"## 📢 增减持 — {now:%Y.%m.%d}\n\n触發清单股票近7天无增减持/质押/解禁公告。\n\n---\n{now:%H:%M}")
    else:
        hits.sort(key=lambda x: x["date"], reverse=True)
        lines = [f"## 📢 增减持联动 — {now:%Y.%m.%d}", "",
                 f"> 只监控触发清单 ｜ 近7天 ｜ 共{len(hits)}条", ""]
        for h in hits:
            lines.append(f"**{h['name']}({h['code']})** ｜ {h['date']} ｜ {h['impact']}")
            lines.append(f"{h['title']}")
            lines.append(f"> {h['summary']}")
            lines.append("")
        push(f"📢 增减持 {now:%Y.%m.%d}（{len(hits)}条）", "\n".join(lines))

    git_commit_state()
    print(f"[DONE] {len(hits)}条命中")


if __name__ == "__main__":
    main()
