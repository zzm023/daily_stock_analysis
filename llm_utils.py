"""
LLM分析工具：DeepSeek V4 Pro API调用 + 框架系统prompt
所有监控脚本共用此模块
模型：deepseek-v4-pro，思考模式由 thinking 参数控制
"""
import os
import requests
import json

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-pro"
ENABLE_THINKING = True   # 思考模式：投资分析建议开（质量优先，成本极低）


FRAMEWORK_SYSTEM = """你是DeepSeek投资框架分析助手。

【核心理念】买垄断，等破产价；收租为主，博弈为辅；左侧分层，本金第一。

【六类属性】
①永续债(核心底仓≤15%)：行政/自然垄断，股息率锚定
②高息成长(防守高息≤8%)：稳定增长+高分红
③周期拐点(周期成长≤3%)：周期底部逆向
④全球寡头(高弹性博弈≤2%)：技术/成本全球领先
⑤品牌心智(防守高息/粘性科技≤8%)：心智垄断
⑥小众冠军(粘性科技≤8%)：细分领域极致

【估值工具】股息率(①/②类)、PE(稳定增长④/⑤类)、PB(周期/金融底③/①类)、PS(科技)。只用多重共振，不孤立。

【交易纪律】
①永续债：触发即买。③周期/科技：目标价打9折、仓位减半、观察1周。
全部：分层买入直接核心仓、现金极致耐心。

【当前资金】60万。

【分析要求】
1. 只基于下面提供的数据，不编造不推测
2. 事实与观点分开，矛盾点明确指出
3. 用块状格式输出，不用表格
4. 判断是否影响触发价或买入建议
5. 缺数据标注"未获取"
"""


def call_deepseek(prompt, temperature=0.1, max_tokens=2048, thinking=ENABLE_THINKING):
    """调用DeepSeek V4 Pro API"""
    if not DEEPSEEK_API_KEY:
        return "[ERROR] 未配置DEEPSEEK_API_KEY"

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": FRAMEWORK_SYSTEM},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if thinking:
        payload["thinking"] = {"type": "enabled"}

    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=300
        )
        data = resp.json()
        if "choices" in data:
            msg = data["choices"][0]["message"]
            return msg.get("content", "")
        else:
            return f"[ERROR] API返回异常: {json.dumps(data, ensure_ascii=False)[:200]}"
    except Exception as e:
        return f"[ERROR] 请求失败: {e}"


def analyze_signal(data_type, data_context, framework_state=None):
    """统一分析入口"""
    prompt = f"【{data_type}】\n\n{data_context}\n\n"

    if framework_state:
        trigger_list = []
        for code, v in framework_state.get("trigger", {}).items():
            if v.get("status") in ("已触发", "接近"):
                trigger_list.append(
                    f"{v['name']}({code}) 触发价{v['trigger_price']} "
                    f"锚定{v['anchor_pct']}% 状态:{v['status']}"
                )
        if trigger_list:
            prompt += "【当前触发清单】\n" + "\n".join(trigger_list) + "\n"

        holdings = framework_state.get("holdings", {})
        if holdings:
            h_list = []
            for k, v in holdings.items():
                if k != "cash" and isinstance(v, dict):
                    h_list.append(f"{v.get('name','')}({k}) {v.get('shares',0)}股 成本{v.get('cost',0)}")
            if h_list:
                prompt += "\n【当前持仓】\n" + "\n".join(h_list) + "\n"

    prompt += """\n请输出：
1. 匹配框架属性
2. 对触发价的影响（需调整？）
3. 买入/持有/卖出建议
4. 风险提示
格式：块状，简洁。"""

    return call_deepseek(prompt)


def load_framework_state(path="framework_state.json"):
    """读取共享状态"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"trigger": {}, "holdings": {}, "events": []}


def save_framework_state(state, path="framework_state.json"):
    """写入共享状态"""
    from datetime import datetime
    state["meta"] = state.get("meta", {})
    state["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    result = call_deepseek("用一句话介绍价值投资。")
    print(result)
