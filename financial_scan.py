"""
财报扫描器 v3
改用 requests params 字典 → 先测单只再看全量
"""
import os, json, requests, re
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

ATTR = {
    "600036":"①永续债","601601":"①永续债","600018":"①永续债",
    "601816":"①永续债","600900":"①永续债","600941":"①永续债",
    "000429":"①永续债","600007":"①永续债",
    "600188":"②高息成长","600585":"②高息成长","300498":"②高息成长",
    "603568":"②高息成长","600598":"②高息成长",
    "000792":"③周期拐点","600299":"③周期拐点","002601":"③周期拐点",
    "603806":"③周期拐点",
    "600309":"④全球寡头","600660":"④全球寡头","601058":"④全球寡头",
    "600406":"④全球寡头","000651":"④全球寡头","000333":"④全球寡头",
    "300124":"④全球寡头",
    "000538":"⑤品牌心智","603605":"⑤品牌心智","605098":"⑤品牌心智",
    "600298":"⑤品牌心智","603288":"⑤品牌心智","002027":"⑤品牌心智",
    "600690":"⑤品牌心智",
    "002508":"⑥小众冠军","002032":"⑥小众冠军","002884":"⑥小众冠军",
    "002318":"⑥小众冠军","603855":"⑥小众冠军","603508":"⑥小众冠军",
    "300628":"⑥小众冠军","000708":"⑥小众冠军","000157":"⑥小众冠军",
    "600031":"⑥小众冠军","600761":"⑥小众冠军","600066":"⑥小众冠军",
    "600486":"⑥小众冠军",
    "688187":"科技⚠","300832":"科技⚠","002837":"科技⚠",
    "300627":"科技⚠","002410":"科技⚠","600845":"科技⚠",
    "002747":"科技⚠","600161":"科技⚠",
}


def fetch_one_stock(code):
    """东财 qt/stock/get + 全财务字段 → 单只测试"""
    prefix = "1" if code.startswith("6") else "0"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": f"{prefix}.{code}",
                "fields": "f43,f57,f58,f37,f38,f39,f40,f41,f42,f55,f173,f183,f184,f185",
            },
            timeout=10,
            headers={"Referer": "https://quote.eastmoney.com/"}
        )
        data = r.json().get("data")
        if not data:
            return None
        return {k: v for k, v in data.items()}
    except Exception as e:
        print(f"  取 {code} 失败: {e}")
        return None


def fetch_financials_batch(codes):
    """东财 push2 批量取财务字段"""
    results = {}
    for code in codes:
        d = fetch_one_stock(code)
        if d:
            results[code] = d
        print(f"  {code} → keys={list(d.keys())[:8] if d else 'NONE'} | f37={d.get('f37') if d else 'N/A'} | f55={d.get('f55') if d else 'N/A'}")
    return results


def batch_prices(codes):
    prices = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i+40]
        symbols = ",".join(f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={symbols}", timeout=15)
            r.encoding = "gbk"
            for c in batch:
                prefix = "sh" if c.startswith("6") else "sz"
                m = re.search(f"v_{prefix}{c}=\"[^\"]*\"", r.text)
                if m:
                    parts = m.group().split("~")
                    if len(parts) >= 4 and parts[3]:
                        prices[c] = float(parts[3])
        except:
            pass
    return prices


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        requests.post("http://www.pushplus.plus/send", json={
            "token": PUSHPLUS_TOKEN, "title": title, "content": content,
            "template": "markdown", "topic": PUSHPLUS_TOPIC,
        }, timeout=10)
    except:
        pass


def main():
    now = datetime.now()
    print(f"[START] 财报扫描器 v3 {now:%Y-%m-%d}")

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    hold = state.get("holdings", {})
    trigger = state.get("trigger", {})

    held = {c for c in hold if c != "cash" and isinstance(hold.get(c), dict)}
    triggered = {c for c, t in trigger.items() if isinstance(t, dict) and t.get("status") == "已触发"}

    codes = sorted(held | triggered)
    print(f"  目标 {len(codes)} 只: {codes}")

    # 先测 1 只看字段
    test = fetch_one_stock(codes[0]) if codes else None
    print(f"\n  测试 {codes[0] if codes else 'N/A'}:")
    if test:
        for k, v in sorted(test.items()):
            print(f"    {k} = {v}")
    else:
        print("    无数据")

    # 全量取
    fin = fetch_financials_batch(codes)
    prices = batch_prices(codes)

    lines = [
        f"财报扫描器 v3 {now:%m}.{now:%d}",
        f"调试模式 | 取 {len(fin)}/{len(codes)} 只",
    ]

    if test:
        lines.append("")
        lines.append("测试字段（招商银行）：")
        for k, v in sorted(test.items())[:15]:
            lines.append(f"  {k} = {v}")

    push(f"财报扫描器 v3 {now:%m}.{now:%d}", "\n".join(lines))
    print(f"[DONE]")


if __name__ == "__main__":
    main()
