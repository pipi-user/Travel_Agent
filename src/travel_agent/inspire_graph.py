"""灵感漫游对话 — LangGraph 状态机。

流程：
  START → greeting → extract_info → check_info ──yes──→ recommend_cities → END
                                           └──no──→ ask_question ──┘
  recommending → select_city → collect_pois → rag_itinerary → generate_itinerary → END
  generating_itinerary → adjust → END
"""
import asyncio
import json
import logging
import re
from typing import Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from typing_extensions import TypedDict

from .llm import get_llm, stream_llm
from .agents.destination import recommend_cities
from .agents.poi_collector import collect_pois_v2
from .agents.itinerary_planner import generate_initial_itinerary
from .memory.memory_agent import retrieve_context, extract_and_save
from .evaluation import evaluate_itinerary

logger = logging.getLogger(__name__)


class InspireChatState(TypedDict, total=False):
    session_id: str
    phase: str
    message: str
    user_info: dict
    asking_field: Optional[str]
    cities: list
    selected_city: Optional[str]
    itinerary: Optional[list]
    user_profile: dict
    memory_block: str
    user_id: str
    tool_results: list
    extracted: dict
    quick_actions: list
    response_text: str
    pois_result: dict
    events: list
    error: Optional[str]
    # P6: 对话历史（供指代消解）
    messages_history: list


def _evt(state: InspireChatState, event_type: str, data: dict) -> dict:
    state["events"].append({"event": event_type, "data": data})
    return state


# ─── 节点函数 ─────────────────────────────────────────

async def node_greeting(state: InspireChatState) -> dict:
    """开场白 — 加载用户记忆，个性化问候。"""
    try:
        from .memory.memory_agent import retrieve_context
        uid = state.get("user_id", "demo")
        ctx = retrieve_context(uid, "", k=6)
        state["user_profile"] = ctx.get("profile", {})
        state["memory_block"] = ctx.get("prompt_block", "")
    except Exception as e:
        logger.warning("加载记忆失败：%s", e)

    profile = state.get("user_profile", {})
    has_memory = any([
        profile.get("allergies"), profile.get("fears"),
        profile.get("dietary"), profile.get("pace_preference"),
    ])

    if has_memory:
        hint_parts = []
        if profile.get("dietary"):
            hint_parts.append(f"忌口{'/'.join(profile['dietary'])}")
        if profile.get("fears"):
            hint_parts.append(f"避免{'/'.join(profile['fears'])}")
        if profile.get("pace_preference"):
            hint_parts.append(f"偏好{profile['pace_preference']}")
        hint = "、".join(hint_parts)
        greeting = f"嗨！又见面啦 🌟\n\n我记得你{hint}。这次想去哪玩？"
    else:
        greeting = (
            "嗨！我是你的旅行助手 🌟\n\n"
            "想去哪玩？跟我说说你的出发地、预算、同行人数，天数，我帮你看看有哪些好去处～"
        )

    state["response_text"] = greeting
    state["quick_actions"] = ["北京出发", "3天预算5000", "帮我推荐几个城市"]
    state["phase"] = "collecting_info"
    _evt(state, "text_chunk", {"content": greeting})
    _evt(state, "quick_actions", {"actions": state["quick_actions"]})
    return state


async def node_extract_info(state: InspireChatState) -> dict:
    """信息提取 — P6 指代消解 + 正则 + LLM 双层。"""
    from .api.routes.inspire import _extract_user_info
    from .target_graph import _resolve_coref

    _evt(state, "tool_call", {"tool": "info_extract", "summary": "正在理解你的需求..."})

    user_info = dict(state.get("user_info", {}))
    message = state.get("message", "")
    asking_field = state.get("asking_field")

    # P6: 指代消解
    history = state.get("messages_history", [])
    resolved = await _resolve_coref(message, history)
    if resolved != message:
        logger.info("P6 指代消解：%r → %r", message, resolved)
        _evt(state, "tool_result", {
            "tool": "coref_resolve",
            "result": f"理解了：{resolved}"
        })
        message = resolved

    user_info = await _extract_user_info(message, user_info, asking_field)

    # 合入画像节奏
    profile = state.get("user_profile", {})
    if not user_info.get("intensity") and profile.get("pace_preference"):
        pace = profile["pace_preference"]
        if pace in ["轻松", "休闲", "慢"]:
            user_info["intensity"] = "边走边躺"
        elif pace in ["紧凑", "特种兵"]:
            user_info["intensity"] = "死了都要逛"

    state["user_info"] = user_info
    state["extracted"] = user_info
    _evt(state, "tool_result", {
        "tool": "info_extract",
        "result": f"已识别：{json.dumps(user_info, ensure_ascii=False)}"
    })
    return state


def edge_check_info(state: InspireChatState) -> str:
    from .api.routes.inspire import _check_info_complete
    complete, _ = _check_info_complete(state.get("user_info", {}))
    return "complete" if complete else "incomplete"


async def node_ask_question(state: InspireChatState) -> dict:
    """追问 — LLM 流式。"""
    from .api.routes.inspire import _check_info_complete, _FIELD_LABELS
    from .api.routes.target_chat import _stream_generate_question

    _evt(state, "tool_call", {"tool": "question_gen", "summary": "正在思考要问你什么..."})

    user_info = state.get("user_info", {})
    _, missing = _check_info_complete(user_info)
    next_field = missing[0] if missing else None
    state["asking_field"] = next_field

    full_text = ""
    async for token in _stream_generate_question(missing, user_info):
        full_text += token
        _evt(state, "text_chunk", {"content": token})

    state["response_text"] = full_text
    state["phase"] = "collecting_info"

    if next_field == "origin":
        state["quick_actions"] = ["北京", "上海", "广州", "深圳", "成都"]
    elif next_field == "companions":
        state["quick_actions"] = ["1个人", "2个人", "一家三口"]
    elif next_field == "days":
        state["quick_actions"] = ["1天", "3天", "5天", "7天"]
    elif next_field == "budget":
        state["quick_actions"] = ["3000", "5000", "8000"]
    else:
        state["quick_actions"] = []

    _evt(state, "quick_actions", {"actions": state["quick_actions"]})
    return state


async def node_recommend_cities(state: InspireChatState) -> dict:
    """城市推荐节点。"""
    user_info = state["user_info"]

    _evt(state, "tool_call", {"tool": "city_recommend", "summary": "正在为你筛选最佳城市..."})

    cities = await asyncio.to_thread(
        recommend_cities,
        origin=user_info["origin"],
        budget=int(user_info["budget"]),
        companions=int(user_info["companions"]),
        days=int(user_info["days"]),
        intensity=user_info.get("intensity", "莫名其妙地玩"),
        preferences=user_info.get("preferences", []),
    )
    state["cities"] = cities

    response_text = f"根据你的需求，我挑了 {len(cities)} 个城市：\n\n"
    response_text += "👇 点卡片看详情，或者直接告诉我你想去哪～"

    state["response_text"] = response_text
    state["phase"] = "recommending"
    state["quick_actions"] = [c["city"] for c in cities[:3]]

    _evt(state, "tool_result", {
        "tool": "city_recommend",
        "result": f"推荐 {len(cities)} 个城市：{', '.join(c['city'] for c in cities[:6])}"
    })
    _evt(state, "text_chunk", {"content": response_text})
    _evt(state, "cities", {"cities": cities})
    _evt(state, "quick_actions", {"actions": state["quick_actions"]})
    return state


async def node_select_and_collect(state: InspireChatState) -> dict:
    """选择城市 + POI 采集 + RAG + 行程生成。"""
    from .api.routes.inspire import _apply_rag_to_itinerary, _enrich_itinerary

    user_info = state["user_info"]
    selected_city = state.get("selected_city", "")

    _evt(state, "tool_call", {"tool": "poi_collect", "summary": f"正在为{selected_city}采集景点、餐厅、酒店..."})

    pois_result = await asyncio.to_thread(
        collect_pois_v2,
        city=selected_city,
        budget=int(user_info["budget"]),
        companions=int(user_info["companions"]),
        days=int(user_info["days"]),
        intensity=user_info.get("intensity", "莫名其妙地玩"),
        preferences=user_info.get("preferences", []),
    )
    state["pois_result"] = pois_result

    _evt(state, "tool_result", {
        "tool": "poi_collect",
        "result": f"采集完成：{len(pois_result.get('pois', []))}个景点, {len(pois_result.get('hotels', []))}家酒店"
    })

    # RAG 精准筛选
    _evt(state, "tool_call", {"tool": "rag_filter", "summary": "正在用语义检索筛选最匹配的景点..."})
    rag_itinerary = await asyncio.to_thread(
        _apply_rag_to_itinerary,
        pois_result,
        user_info.get("preferences", []),
        selected_city,
        int(user_info["days"]),
        user_info.get("intensity", "莫名其妙地玩"),
    )
    pois_result["initial_itinerary"] = rag_itinerary

    itinerary = _enrich_itinerary(
        rag_itinerary,
        pois_result.get("pois", []),
        pois_result.get("hotels", []),
    )
    state["itinerary"] = itinerary
    state["phase"] = "generating_itinerary"

    _evt(state, "tool_result", {"tool": "rag_filter", "result": "语义筛选完成"})
    _evt(state, "tool_call", {"tool": "itinerary_gen", "summary": "正在生成最优行程..."})
    _evt(state, "tool_result", {"tool": "itinerary_gen", "result": "行程生成完成"})

    # P0: 行程完成后沉淀记忆
    try:
        trip_data = {
            "city": selected_city,
            "days": user_info.get("days"),
            "budget": user_info.get("budget"),
            "companions": user_info.get("companions"),
            "preferences": user_info.get("preferences", []),
            "itinerary_summary": f"{selected_city} {user_info.get('days')}天行程",
        }
        await asyncio.to_thread(
            extract_and_save, state.get("session_id", "default"), trip_data
        )
        logger.info("记忆沉淀完成：%s", state.get("session_id"))
    except Exception as e:
        logger.warning("记忆沉淀失败：%s", e)

    # P5: 行程质量评估
    eval_result = {}
    try:
        eval_result = evaluate_itinerary(itinerary, user_info, pois_result.get("pois", []))
        logger.info("行程评分：%s", eval_result)
        _evt(state, "tool_result", {
            "tool": "quality_eval",
            "result": f"质量评分：{eval_result['overall']:.0%} — {eval_result['summary']}"
        })
    except Exception as e:
        logger.warning("行程评估失败：%s", e)

    response_text = f"✨ {selected_city} {user_info['days']}天行程出来了！\n\n"
    response_text += "你可以：\n• 看每日安排\n• 调整景点\n• 确认并导出"

    # P5: 评分摘要
    if eval_result.get("overall"):
        response_text += f"\n\n📊 行程质量：{eval_result['overall']:.0%} — {eval_result.get('summary', '')}"

    state["response_text"] = response_text
    state["quick_actions"] = ["查看详细行程", "调整景点", "重新推荐城市"]

    _evt(state, "text_chunk", {"content": response_text})
    _evt(state, "itinerary", {"itinerary": itinerary})
    _evt(state, "quick_actions", {"actions": state["quick_actions"]})
    return state


# ─── P1: 行程智能调整 ───────────────────────────────

_ADJUST_PROMPT = """你是旅行行程调整助手。用户想修改当前行程。

【当前行程】
{itinerary_json}

【用户要求】
{user_request}

【任务】
根据用户要求修改行程。规则：
1. 如果用户说“去掉/删除/不要”某个景点，从行程中移除它
2. 如果用户说“加/换成”某类景点，在合适的时间段插入
3. 如果用户说“重新生成”，返回空行程 []
4. 保持其他景点不变
5. 只返回修改后的行程 JSON，不要解释

【输出格式】严格返回 JSON 数组：
[
  {{"day": 1, "items": [...], "total_cost": 0}}
]
只输出 JSON，不要解释。"""


async def node_adjust_itinerary(state: InspireChatState) -> dict:
    """P1: LLM 理解用户调整指令并修改行程。"""
    itinerary = state.get("itinerary", [])
    message = state.get("message", "")

    _evt(state, "tool_call", {
        "tool": "itinerary_adjust",
        "summary": f"正在理解调整需求：{message[:30]}..."
    })

    try:
        llm = get_llm(json_mode=True)
        prompt = _ADJUST_PROMPT.format(
            itinerary_json=json.dumps(itinerary, ensure_ascii=False)[:2000],
            user_request=message,
        )
        resp = await asyncio.to_thread(llm.invoke, prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()

        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("LLM 未返回有效 JSON")

        new_itinerary = json.loads(raw[start:end + 1])

        if not new_itinerary:
            state["response_text"] = "好的，重新帮你规划～"
            state["phase"] = "collecting_info"
            state["itinerary"] = None
            _evt(state, "text_chunk", {"content": "好的，重新规划！你还想去哪些地方？"})
            return state

        state["itinerary"] = new_itinerary
        old_count = sum(len(d.get("items", [])) for d in itinerary)
        new_count = sum(len(d.get("items", [])) for d in new_itinerary)
        diff = old_count - new_count
        if diff > 0:
            summary = f"好的，已帮你去掉 {diff} 个景点 ✨"
        elif diff < 0:
            summary = f"好的，已帮你加了 {-diff} 个新景点 ✨"
        else:
            summary = "好的，行程已调整 ✨"

        state["response_text"] = summary
        state["quick_actions"] = ["查看详细行程", "继续调整", "确认行程"]
        _evt(state, "tool_result", {"tool": "itinerary_adjust", "result": f"调整完成：{new_count}个景点"})
        _evt(state, "text_chunk", {"content": summary})
        _evt(state, "itinerary", {"itinerary": new_itinerary})
        _evt(state, "quick_actions", {"actions": state["quick_actions"]})

    except Exception as e:
        logger.warning("行程调整失败：%s", e)
        state["response_text"] = "抱歉，没能理解你的意思。可以试试：\n• 告诉我去掉哪个景点\n• 告诉我加什么类型的景点"
        state["quick_actions"] = ["重新生成", "确认行程"]
        _evt(state, "text_chunk", {"content": state["response_text"]})
        _evt(state, "quick_actions", {"actions": state["quick_actions"]})

    return state


# ─── 构建图 ──────────────────────────────────────────

def build_inspire_graph() -> StateGraph:
    graph = StateGraph(InspireChatState)

    graph.add_node("greeting", node_greeting)
    graph.add_node("extract_info", node_extract_info)
    graph.add_node("ask_question", node_ask_question)
    graph.add_node("recommend_cities", node_recommend_cities)
    graph.add_node("select_and_collect", node_select_and_collect)

    graph.add_edge(START, "greeting")
    graph.add_edge("greeting", "extract_info")

    graph.add_conditional_edges(
        "extract_info",
        edge_check_info,
        {
            "complete": "recommend_cities",
            "incomplete": "ask_question",
        },
    )

    graph.add_edge("ask_question", END)
    graph.add_edge("recommend_cities", END)
    graph.add_edge("select_and_collect", END)

    return graph


def create_compiled_inspire_graph():
    graph = build_inspire_graph()
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


_compiled_graph = None

def get_inspire_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = create_compiled_inspire_graph()
    return _compiled_graph
