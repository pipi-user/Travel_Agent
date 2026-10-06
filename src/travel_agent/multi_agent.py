"""多 Agent 协作架构 — Supervisor + 子 Agent 模式。

将原单体 LangGraph 拆分为 4 个专业 Agent：
  - IntentAgent:   意图解析 + 指代消解 + 信息提取
  - ResearchAgent: 目的地研究 + POI 采集 + RAG 检索
  - PlanningAgent: 行程生成 + 智能调整 + 质量评估
  - Supervisor:    路由调度，决定下一个 Agent

每个 Agent 是独立的 LangGraph 子图，由 Supervisor 统一编排。
"""
import asyncio
import json
import logging
from typing import Optional, Literal

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from typing_extensions import TypedDict

from .llm import get_llm
from .agents.poi_collector import collect_pois_v2
from .agents.itinerary_planner import generate_initial_itinerary
from .memory.poi_vector_store import index_pois, search_pois, count_pois
from .memory.memory_agent import retrieve_context, extract_and_save
from .evaluation import evaluate_itinerary

logger = logging.getLogger(__name__)


# ─── 全局状态（Supervisor 级） ─────────────────────

class MultiAgentState(TypedDict, total=False):
    session_id: str
    message: str
    phase: str
    user_info: dict
    itinerary: Optional[list]
    pois_result: dict
    events: list
    next_agent: str          # intent / research / planning / done
    messages_history: list
    response_text: str
    quick_actions: list
    error: Optional[str]


# ─── Agent 1: IntentAgent ──────────────────────────

async def intent_agent(state: MultiAgentState) -> dict:
    """意图解析 Agent — 指代消解 + 信息提取 + 追问生成。"""
    from .target_graph import _resolve_coref, _COREF_KEYWORDS
    from .api.routes.target_chat import _regex_extract, _extract_user_info, _check_info_complete, _stream_generate_question

    message = state.get("message", "")
    user_info = dict(state.get("user_info", {}))
    history = state.get("messages_history", [])

    # 1. 指代消解
    resolved = await _resolve_coref(message, history)
    if resolved != message:
        state["events"].append({
            "event": "tool_result",
            "data": {"tool": "coref_resolve", "result": f"理解了：{resolved}"}
        })
        message = resolved

    # 2. 信息提取
    state["events"].append({
        "event": "tool_call",
        "data": {"tool": "intent_parse", "summary": "正在理解你的需求..."}
    })
    _regex_extract(message, user_info)
    user_info = await _extract_user_info(message, user_info, None)
    state["user_info"] = user_info

    state["events"].append({
        "event": "tool_result",
        "data": {"tool": "intent_parse", "result": f"已识别：{json.dumps(user_info, ensure_ascii=False)}"}
    })

    # 3. 判断信息是否完整
    complete, missing = _check_info_complete(user_info)
    if complete:
        state["next_agent"] = "research"
    else:
        # 生成追问
        state["events"].append({
            "event": "tool_call",
            "data": {"tool": "question_gen", "summary": "正在思考要问你什么..."}
        })
        full_text = ""
        async for token in _stream_generate_question(missing, user_info):
            full_text += token
            state["events"].append({"event": "text_chunk", "data": {"content": token}})

        state["response_text"] = full_text
        state["next_agent"] = "done"  # 等用户回复

    return state


# ─── Agent 2: ResearchAgent ────────────────────────

async def research_agent(state: MultiAgentState) -> dict:
    """研究 Agent — 目的地搜索 + POI 采集 + RAG 检索。"""
    user_info = state["user_info"]
    city = user_info["dest_city"]

    # 1. 目的地研究
    state["events"].append({
        "event": "tool_call",
        "data": {"tool": "destination_research", "summary": f"正在搜索{city}的旅游特色..."}
    })

    from .api.routes.target_chat import _agent_research_destination
    tool_calls = await _agent_research_destination(city, user_info.get("preferences", []))
    for tc in tool_calls:
        state["events"].append({
            "event": "tool_result",
            "data": {"tool": tc["tool"], "result": tc["result"]}
        })

    # 2. POI 采集
    state["events"].append({
        "event": "tool_call",
        "data": {"tool": "poi_collect", "summary": f"正在为{city}采集景点、餐厅、酒店..."}
    })

    pois_result = await asyncio.to_thread(
        collect_pois_v2,
        city=city,
        budget=int(user_info["budget"]),
        companions=int(user_info["companions"]),
        days=int(user_info["days"]),
        intensity=user_info.get("intensity", "莫名其妙地玩"),
        preferences=user_info.get("preferences", []),
    )
    state["pois_result"] = pois_result

    state["events"].append({
        "event": "tool_result",
        "data": {
            "tool": "poi_collect",
            "result": f"采集完成：{len(pois_result.get('pois', []))}个景点, {len(pois_result.get('hotels', []))}家酒店"
        }
    })

    # 3. RAG 语义检索
    preferences = user_info.get("preferences", [])
    all_pois = pois_result.get("pois", []) + pois_result.get("hotels", [])
    existing_count = await asyncio.to_thread(count_pois, city)
    if existing_count < len(all_pois) * 0.5:
        await asyncio.to_thread(index_pois, all_pois, city)

    if preferences:
        rag_query = f"{city} {' '.join(preferences)} 旅行推荐"
        state["events"].append({
            "event": "tool_call",
            "data": {"tool": "rag_search", "summary": f"正在语义检索..."}
        })
        rag_results = await asyncio.to_thread(search_pois, rag_query, city, 15)
        rag_ids = {r["id"] for r in rag_results[:10]}
        for poi in all_pois:
            if poi["id"] in rag_ids:
                poi["score"] = poi.get("score", 0) + 1.5

        state["events"].append({
            "event": "tool_result",
            "data": {"tool": "rag_search", "result": f"语义匹配 {len(rag_ids)} 个高相关 POI"}
        })

    state["next_agent"] = "planning"
    return state


# ─── Agent 3: PlanningAgent ────────────────────────

async def planning_agent(state: MultiAgentState) -> dict:
    """规划 Agent — 行程生成 + 评估 + 记忆沉淀。"""
    user_info = state["user_info"]
    pois_result = state.get("pois_result", {})

    state["events"].append({
        "event": "tool_call",
        "data": {"tool": "itinerary_gen", "summary": "正在生成最优行程..."}
    })

    initial_itinerary = pois_result.get("initial_itinerary", [])
    from .api.routes.target_chat import _enrich_itinerary
    itinerary = _enrich_itinerary(
        initial_itinerary,
        pois_result.get("pois", []),
        pois_result.get("hotels", []),
    )
    state["itinerary"] = itinerary

    state["events"].append({
        "event": "tool_result",
        "data": {"tool": "itinerary_gen", "result": "行程生成完成"}
    })

    # 质量评估
    try:
        eval_result = evaluate_itinerary(itinerary, user_info, pois_result.get("pois", []))
        state["events"].append({
            "event": "tool_result",
            "data": {"tool": "quality_eval", "result": f"质量评分：{eval_result['overall']:.0%}"}
        })
    except Exception:
        eval_result = {}

    # 记忆沉淀（异步）
    try:
        trip_data = {
            "city": user_info.get("dest_city"),
            "days": user_info.get("days"),
            "budget": user_info.get("budget"),
            "preferences": user_info.get("preferences", []),
        }
        await asyncio.to_thread(extract_and_save, state.get("session_id", "default"), trip_data)
    except Exception:
        pass

    # 生成摘要
    dest = user_info["dest_city"]
    days = user_info["days"]
    n_items = sum(len(d.get("items", [])) for d in itinerary)
    result_text = (
        f"✨ {dest} {days}天行程出来了！\n\n"
        f"安排了 {n_items} 个站点/天。\n\n"
        "你可以：\n• 查看详细行程\n• 调整景点\n• 导出保存"
    )
    if eval_result.get("overall"):
        result_text += f"\n\n📊 行程质量：{eval_result['overall']:.0%} — {eval_result.get('summary', '')}"

    state["response_text"] = result_text
    state["quick_actions"] = ["查看详细行程", "调整景点", "重新规划"]
    state["events"].append({"event": "text_chunk", "data": {"content": result_text}})
    state["events"].append({"event": "itinerary", "data": {"itinerary": itinerary}})
    state["events"].append({"event": "quick_actions", "data": {"actions": state["quick_actions"]}})
    state["next_agent"] = "done"
    return state


# ─── Supervisor: 路由调度 ──────────────────────────

def supervisor_route(state: MultiAgentState) -> str:
    """Supervisor 路由 — 根据 next_agent 决定下一步。"""
    next_agent = state.get("next_agent", "done")
    if next_agent == "intent":
        return "intent_agent"
    elif next_agent == "research":
        return "research_agent"
    elif next_agent == "planning":
        return "planning_agent"
    return "__end__"


def build_multi_agent_graph() -> StateGraph:
    """构建多 Agent 协作图。"""
    graph = StateGraph(MultiAgentState)

    # 添加 Agent 节点
    graph.add_node("intent_agent", intent_agent)
    graph.add_node("research_agent", research_agent)
    graph.add_node("planning_agent", planning_agent)

    # Supervisor 路由
    graph.add_conditional_edges(
        START,
        supervisor_route,
        {
            "intent_agent": "intent_agent",
            "research_agent": "research_agent",
            "planning_agent": "planning_agent",
            "__end__": END,
        },
    )

    # 每个 Agent 完成后回到 Supervisor
    graph.add_conditional_edges(
        "intent_agent",
        supervisor_route,
        {
            "research_agent": "research_agent",
            "planning_agent": "planning_agent",
            "__end__": END,
        },
    )
    graph.add_conditional_edges(
        "research_agent",
        supervisor_route,
        {
            "planning_agent": "planning_agent",
            "__end__": END,
        },
    )
    graph.add_conditional_edges(
        "planning_agent",
        lambda s: "__end__",
        {"__end__": END},
    )

    return graph


def create_multi_agent():
    """创建编译后的多 Agent 图。"""
    graph = build_multi_agent_graph()
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# 单例
_multi_agent = None

def get_multi_agent():
    global _multi_agent
    if _multi_agent is None:
        _multi_agent = create_multi_agent()
    return _multi_agent
