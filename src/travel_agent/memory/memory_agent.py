"""记忆系统统一出口：检索 / 提取 / 注入。"""
import json
import re

from ..llm import get_llm
from .store import load_profile, save_profile
from .vector_store import add_memories_bulk, search_memories


# ============ 读取：规划前拉取上下文 ============

def retrieve_context(
    user_id: str,
    query: str = "",
    k: int = 6,
) -> dict:
    """规划前调用。返回 {profile, memories, prompt_block}。"""
    profile = load_profile(user_id) or {}
    memories = search_memories(user_id, query or "旅行偏好", k=k)
    return {
        "profile": profile,
        "memories": memories,
        "prompt_block": format_for_prompt(profile, memories),
    }


def format_for_prompt(profile: dict, memories: list[dict]) -> str:
    """把画像 + 记忆拼成给 LLM 的文本块。"""
    lines = []

    # 健康/硬约束
    hard = []
    if profile.get("allergies"):
        hard.append(f"过敏：{'、'.join(profile['allergies'])}")
    if profile.get("fears"):
        hard.append(f"恐惧：{'、'.join(profile['fears'])}")
    if profile.get("dietary"):
        hard.append(f"饮食禁忌：{'、'.join(profile['dietary'])}")
    if hard:
        lines.append("【硬约束（必须遵守）】" + " | ".join(hard))

    # 一般偏好
    if profile.get("pace_preference"):
        lines.append(f"【节奏偏好】{profile['pace_preference']}")

    # 分类记忆
    grouped = {}
    for m in memories:
        grouped.setdefault(m["type"], []).append(m["text"])

    labels = {
        "visited":   "去过 / 体验过",
        "liked":     "明确喜欢",
        "disliked":  "明确不喜欢",
        "preference": "一般偏好",
        "note":      "备注",
    }
    for t, label in labels.items():
        if grouped.get(t):
            lines.append(f"【{label}】" + "；".join(grouped[t][:4]))

    return "\n".join(lines) if lines else "（暂无历史记忆）"


# ============ 写入：从行程/反馈中提取记忆 ============

EXTRACT_PROMPT = """你是用户记忆提取器。从下面这次旅行信息中，提取**值得长期记住**的用户事实。

【行程】
{trip_text}

【用户反馈】
{feedback}

【提取规则】
1. 只记**真实出现**的、对以后规划有用的
2. 每条记忆 type 从以下选一个：
   - visited: 去过的地方 / 吃过的餐厅（含时间）
   - liked: 明确表示喜欢的
   - disliked: 明确表示不喜欢的
   - preference: 一般偏好（"喜欢历史建筑"）
   - note: 其他备注（健康、习惯、同行情况）
3. 一条记忆只讲一件事，简洁（20 字内）
4. 最多输出 8 条

【输出格式】严格返回 JSON 数组：
[
  {{"type": "visited", "text": "2026-09 去过汕头小公园", "metadata": {{"city": "汕头", "poi": "小公园"}}}},
  {{"type": "liked", "text": "喜欢汕头牛肉火锅", "metadata": {{"city": "汕头"}}}},
  {{"type": "disliked", "text": "不喜欢排队久的餐厅", "metadata": {{}}}}
]

只输出 JSON 数组，不要解释。"""


def extract_and_save(
    user_id: str,
    trip: dict,
    feedback: str = "",
) -> int:
    """行程完成后调用。返回写入条数。"""
    trip_text = json.dumps(trip, ensure_ascii=False)[:3000]

    try:
        llm = get_llm(json_mode=True)
        prompt = EXTRACT_PROMPT.format(
            trip_text=trip_text,
            feedback=feedback or "（用户未填反馈）",
        )
        resp = llm.invoke(prompt)
        text = resp.content.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        s, e = text.find("["), text.rfind("]")
        if s == -1 or e == -1:
            return 0
        items = json.loads(text[s:e + 1])
        if not isinstance(items, list):
            return 0
        return add_memories_bulk(user_id, items)
    except Exception:
        return 0


# ============ 快捷写入：前端点赞/差评 ============

def mark_liked(user_id: str, poi_name: str, city: str, note: str = "") -> int:
    from .vector_store import add_memory
    return add_memory(
        user_id, "liked",
        note or f"喜欢 {city} 的 {poi_name}",
        {"city": city, "poi": poi_name},
    )


def mark_disliked(user_id: str, poi_name: str, city: str, reason: str = "") -> int:
    from .vector_store import add_memory
    return add_memory(
        user_id, "disliked",
        f"不喜欢 {city} 的 {poi_name}" + (f"：{reason}" if reason else ""),
        {"city": city, "poi": poi_name},
    )


def mark_visited(user_id: str, poi_name: str, city: str, date: str = "") -> int:
    from .vector_store import add_memory
    return add_memory(
        user_id, "visited",
        f"{date + ' ' if date else ''}去过 {city} 的 {poi_name}",
        {"city": city, "poi": poi_name, "date": date},
    )