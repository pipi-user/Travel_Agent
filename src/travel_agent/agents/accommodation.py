from ..state import TravelState
from ..tools.amap import search_hotel
from ..tools.search import web_search
from ..llm import get_llm
import json
import re

def accommodation_agent(state: TravelState) -> dict:
    """住宿推荐子Agent"""
    city = state.get("selected_city")
    if not city:
        return {"accommodation": []}

    budget = state["request"].get("budget", 0)
    profile = state.get("user_profile", {}) or {}
    pace = profile.get("pace_preference") or state["request"].get("pace", "适中")

    # 1. 高德搜酒店
    try:
        hotel_raw = search_hotel.invoke({"city": city, "keywords": "酒店"})
    except Exception as e:
        hotel_raw = f"高德搜索失败：{e}"

    # 2. Tavily 搜住宿攻略
    try:
        web_raw = web_search.invoke(f"{city} 住宿推荐 民宿 性价比 {pace}")
    except Exception as e:
        web_raw = f"网搜失败：{e}"

    # 3. LLM 整合
    llm = get_llm()
    prompt = f"""你是资深旅游规划师。用户在「{city}」需要住宿推荐，总预算 {budget} 元，节奏偏好「{pace}」。

高德搜索结果：
{hotel_raw}

网搜攻略：
{web_raw}

请推荐 3 个住宿选项，**只输出 JSON 数组**，每个元素字段：
- name: 名称
- address: 地址
- rating: 评分（字符串，没有就填"暂无"）
- price: 每晚参考价（字符串，如 "300元/晚"，没有就填"暂无"）
- reason: 一句推荐理由，不超过 30 字

只输出 JSON 数组，不要解释、不要 markdown 代码块。"""

    try:
        res = llm.invoke(prompt)
        content = res.content.strip()
        content = re.sub(r"^```(json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
        data = json.loads(content)
        if not isinstance(data, list):
            data = [data]
        return {"accommodation": data}
    except Exception as e:
        return {"accommodation": []}