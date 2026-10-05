"""行程调整 Agent — LLM 决定意图 + 调用工具执行。"""
import json
import logging
import re

from ..llm import get_llm

logger = logging.getLogger(__name__)


INTENT_PROMPT = """你是行程调整助手。用户会提出行程修改需求，你要解析成结构化操作。

【当前行程】
{itinerary_text}

【可用操作】
1. replace（替换）：用户想换掉某个 POI
   字段：action, target（要替换的 POI 名）, requirement（新 POI 的要求）
2. remove（删除）：用户想删掉某个 POI
   字段：action, target（POI 名）
3. add（添加）：用户想新增一个 POI
   字段：action, requirement（类型描述）, day（可选）
4. reroute（重排）：用户想调整顺序
   字段：action, day（可选）
5. unknown：无法解析

【输出格式】
严格输出 JSON，如：
{{"action": "replace", "target": "西湖公园", "requirement": "安静的公园"}}

【示例】
"换掉西湖公园，换个安静的公园"
→ {{"action": "replace", "target": "西湖公园", "requirement": "安静的公园"}}
"第2天加一个博物馆"
→ {{"action": "add", "requirement": "博物馆", "day": 2}}
"把潮州古城删掉"
→ {{"action": "remove", "target": "潮州古城"}}

只输出 JSON，不要解释。现在解析：
{user_message}
"""


def _format_itinerary(itinerary: list[dict], poi_map: dict) -> str:
    lines = []
    period_map = {"morning": "早", "noon": "中", "afternoon": "下午", "evening": "晚"}
    for day in itinerary:
        lines.append(f"第{day['day']}天：")
        for item in day.get("items", []):
            poi = poi_map.get(item["poi_id"], {})
            name = poi.get("name", item["poi_id"])
            period = item.get("period", "")
            lines.append(f"  [{period_map.get(period, period)}] {name}")
    return "\n".join(lines)


def parse_adjust_intent(message: str, itinerary: list[dict], poi_map: dict) -> dict:
    """解析用户调整意图。"""
    itinerary_text = _format_itinerary(itinerary, poi_map)
    llm = get_llm(json_mode=True)

    prompt = INTENT_PROMPT.format(
        itinerary_text=itinerary_text,
        user_message=message,
    )

    try:
        resp = llm.invoke(prompt)
        content = resp.content.strip()
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
        s, e = content.find("{"), content.rfind("}")
        if s != -1 and e != -1:
            content = content[s:e + 1]
        data = json.loads(content)
        logger.info("解析调整意图：%s", data)
        return data
    except Exception as ex:
        logger.warning("解析调整意图失败：%s", ex)
        return {"action": "unknown"}


def execute_adjust(
    intent: dict,
    itinerary: list[dict],
    pois: list[dict],
    city: str,
) -> tuple[list[dict], str]:
    """执行调整。返回 (新行程, 回复文本)。"""
    action = intent.get("action", "unknown")
    target = intent.get("target", "")
    requirement = intent.get("requirement", "")
    day_num = intent.get("day")

    if action == "unknown":
        return itinerary, "目前无法解析。可以试试：\n• 换掉 XX，换个 XX\n• 第 X 天加一个 XX\n• 删掉 XX"

    if action == "remove":
        for d in itinerary:
            for it in list(d["items"]):
                poi = next((p for p in pois if p["id"] == it["poi_id"]), None)
                if poi and poi["name"] == target:
                    d["items"].remove(it)
                    return itinerary, f"✅ 已删除「{target}」"
        return itinerary, f"没找到「{target}」"

    if action == "replace":
        old_day = old_item = old_poi = None
        for d in itinerary:
            for it in d["items"]:
                poi = next((p for p in pois if p["id"] == it["poi_id"]), None)
                if poi and poi["name"] == target:
                    old_day, old_item, old_poi = d, it, poi
                    break
            if old_day:
                break

        if not old_day:
            return itinerary, f"没找到「{target}」"

        from ..memory.poi_vector_store import search_pois
        hits = search_pois(requirement or target, city, k=10)

        existing_ids = {it["poi_id"] for d in itinerary for it in d["items"]}

        new_poi = None
        for h in hits:
            if h["id"] in existing_ids:
                continue
            if h["poi_type"] == old_poi["poi_type"]:
                new_poi = h
                break

        if not new_poi:
            # 放宽类型限制
            new_poi = next((h for h in hits if h["id"] not in existing_ids), None)

        if not new_poi:
            return itinerary, f"没找到符合「{requirement}」的替代"

        old_item["poi_id"] = new_poi["id"]
        return itinerary, f"✅ 已把「{target}」换成「{new_poi['name']}」"

    if action == "add":
        if not requirement:
            return itinerary, "请告诉我要加什么样的 POI"

        from ..memory.poi_vector_store import search_pois
        hits = search_pois(requirement, city, k=10)

        existing_ids = {it["poi_id"] for d in itinerary for it in d["items"]}
        new_poi = next((h for h in hits if h["id"] not in existing_ids), None)
        if not new_poi:
            return itinerary, f"没找到符合「{requirement}」的 POI"

        target_day = None
        if day_num:
            target_day = next((d for d in itinerary if d["day"] == day_num), None)
        if not target_day:
            target_day = min(itinerary, key=lambda d: len(d["items"]))

        period = "noon" if new_poi["poi_type"] == "food" else "afternoon"
        target_day["items"].append({"poi_id": new_poi["id"], "period": period})
        return itinerary, f"✅ 已加入「{new_poi['name']}」到第{target_day['day']}天"

    if action == "reroute":
        return itinerary, "重排功能开发中～"

    return itinerary, "暂时不支持这个操作"