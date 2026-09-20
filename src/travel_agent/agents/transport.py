from ..state import TravelState
from ..tools.search import web_search
from ..llm import get_llm
import json
import re

def transport_agent(state: TravelState) -> dict:
    """交通规划子Agent：根据出发地和目的地给交通方案"""
    origin = state["request"].get("origin", "")
    dest = state.get("selected_city")
    if not origin or not dest:
        return {"transport": None}

    budget = state["request"].get("budget", 0)

    # 1. 调 Tavily 搜交通攻略
    try:
        web_raw = web_search.invoke(f"{origin} 到 {dest} 交通 高铁 飞机 推荐 票价")
    except Exception as e:
        web_raw = f"搜索失败：{e}"
    # 2. LLM 整合为结构化 JSON
    llm = get_llm()
    prompt = f"""你是资深交通规划师。用户从「{origin}」前往「{dest}」，总预算 {budget} 元。

搜索信息：
{web_raw}

请给出**三段式交通方案**，**只输出 JSON**：
- intercity: 城际交通（字段：mode 交通方式、route 路线、duration 耗时、cost 费用、tips 建议）
- arrival: 落地/到站后到市区酒店的交通（字段：mode、duration、cost、tips）
- local: 市内交通总体建议（字段：mode 推荐方式、cost 日均费用、tips 建议）

格式示例：
{{
  "intercity": {{"mode": "飞机", "route": "深圳宝安→成都天府", "duration": "约2.5小时", "cost": 1200, "tips": "提前2周订"}},
  "arrival": {{"mode": "地铁/打车", "duration": "约50分钟", "cost": 60, "tips": "地铁18号线到市区"}},
  "local": {{"mode": "地铁+打车", "cost": 80, "tips": "办一张天府通卡"}}
}}

只输出 JSON 对象，不要解释或 markdown 代码块。"""

    try:
        res = llm.invoke(prompt)
        content = res.content.strip()
        content = re.sub(r"^```(json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
        data = json.loads(content)
        return {"transport": data}
    except Exception as e:
        return {"transport": {
            "mode": "未知",
            "route": f"{origin} -> {dest}",
            "duration": "未知",
            "cost": 0,
            "tips": f"解析失败：{e}",
        }}