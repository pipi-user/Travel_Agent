"""定向定制对话 — LangGraph 状态机。

将原 phase 字符串流转重构为 LangGraph 图结构：
  START → greeting → extract_info → check_info ──yes──→ research → collect_pois → rag_search → generate_itinerary → END
                                           └──no──→ ask_question ──┘
  generating_itinerary 阶段：adjust_itinerary → END
"""
import asyncio
import json
import logging
import re
from typing import Optional, Any

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from typing_extensions import TypedDict

from .llm import get_llm
from .agents.poi_collector import collect_pois_v2
from .agents.itinerary_planner import generate_initial_itinerary
from .memory.poi_vector_store import index_pois, search_pois, count_pois
from .memory.memory_agent import retrieve_context, extract_and_save

logger = logging.getLogger(__name__)


# ─── 图状态 ──────────────────────────────────────────

class TargetChatState(TypedDict, total=False):
    """对话图全局状态。"""
    session_id: str
    phase: str                    # greeting / collecting_info / generating_itinerary
    message: str                  # 用户最新输入
    user_info: dict
    asking_field: Optional[str]
    itinerary: Optional[list]
    tool_results: list
    # LLM 提取的增量信息
    extracted: dict
    # 追问文本
    question_text: str
    # 快捷操作
    quick_actions: list
    # 助手回复文本
    response_text: str
    # POI 采集结果
    pois_result: dict
    # 事件队列（供 SSE 消费）
    events: list
    # 错误信息
    error: Optional[str]
    # P6: 对话历史（供指代消解）
    messages_history: list


# ─── 辅助：追加事件 ──────────────────────────────────

def _evt(state: TargetChatState, event_type: str, data: dict) -> dict:
    """往 events 队列追加一条 SSE 事件。"""
    state["events"].append({"event": event_type, "data": data})
    return state


# ─── 节点函数 ─────────────────────────────────────────

async def node_greeting(state: TargetChatState) -> dict:
    """开场白节点 — 含历史记忆加载。"""
    # P0: 加载用户历史记忆
    session_id = state.get("session_id", "default")
    memory_block = ""
    try:
        ctx = retrieve_context(session_id, "旅行偏好", k=4)
        memory_block = ctx.get("prompt_block", "")
        if memory_block and memory_block != "（暂无历史记忆）":
            state["user_info"]["_memory_context"] = memory_block
            logger.info("加载用户记忆：%s", session_id)
    except Exception as e:
        logger.warning("记忆加载失败（不影响对话）：%s", e)

    greeting = (
        "你好呀～ 告诉我你的旅行想法，我来帮你规划 ✨\n"
        "想去哪里、玩几天、几个人、大概预算，说个大概就行～\n"
        "比如：想去成都吃火锅，3天，2个人，预算5000"
    )
    # 如果有历史记忆，追加提示
    if memory_block and memory_block != "（暂无历史记忆）":
        greeting += "\n\n📖 我记住了你上次的偏好，这次会推荐得更准～"

    state["response_text"] = greeting
    state["quick_actions"] = ["想去成都", "想去海边", "想看历史古迹"]
    state["phase"] = "collecting_info"
    _evt(state, "text_chunk", {"content": greeting})
    _evt(state, "quick_actions", {"actions": state["quick_actions"]})
    return state


# ─── P6: 指代消解 ─────────────────────────────────

_COREF_PROMPT = """你是对话理解助手。用户说了一句话，可能包含指代词（这个、那个、它、这里、上面那个等）。

【对话历史】
{history}

【用户最新输入】
{message}

【任务】
如果用户输入包含指代词，请将其替换为具体指代的内容，返回消解后的完整句子。
如果没有指代词，直接返回原句。

只返回消解后的句子，不要解释。"""

_COREF_KEYWORDS = ["这个", "那个", "它", "这里", "那里", "上面", "刚才", "刚刚", "前者", "后者"]


async def _resolve_coref(message: str, messages_history: list[dict]) -> str:
    """P6: 指代消解 — 如果消息包含指代词，用 LLM 解析指代。"""
    has_coref = any(kw in message for kw in _COREF_KEYWORDS)
    if not has_coref:
        return message

    try:
        # 取最近 4 轮对话作为上下文
        recent = messages_history[-8:] if len(messages_history) > 8 else messages_history
        history_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:80]}"
            for m in recent if m.get("content")
        )
        llm = get_llm()
        prompt = _COREF_PROMPT.format(history=history_text, message=message)
        resp = await asyncio.to_thread(llm.invoke, prompt)
        resolved = (resp.content if hasattr(resp, "content") else str(resp)).strip()
        if resolved and len(resolved) < len(message) * 3:
            logger.info("指代消解：%r → %r", message, resolved)
            return resolved
    except Exception as e:
        logger.warning("指代消解失败：%s", e)

    return message


async def node_extract_info(state: TargetChatState) -> dict:
    """信息提取节点 — P6 指代消解 + 正则 + LLM 双层提取。"""
    from .api.routes.target_chat import _regex_extract, _extract_user_info

    _evt(state, "tool_call", {"tool": "info_extract", "summary": "正在理解你的需求..."})

    user_info = dict(state.get("user_info", {}))
    message = state.get("message", "")
    asking_field = state.get("asking_field")

    # P6: 指代消解 — 用对话历史解析“这个”“那个”等指代词
    history = state.get("messages_history", [])
    resolved_message = await _resolve_coref(message, history)
    if resolved_message != message:
        logger.info("P6 指代消解：%r → %r", message, resolved_message)
        _evt(state, "tool_result", {
            "tool": "coref_resolve",
            "result": f"理解了：{resolved_message}"
        })
        message = resolved_message

    # 正则提取
    _regex_extract(message, user_info)
    # LLM 提取
    user_info = await _extract_user_info(message, user_info, asking_field)
    state["user_info"] = user_info
    state["extracted"] = user_info

    _evt(state, "tool_result", {
        "tool": "info_extract",
        "result": f"已识别：{json.dumps(user_info, ensure_ascii=False)}"
    })
    return state


def edge_check_info(state: TargetChatState) -> str:
    """条件边：信息是否收集完整。"""
    from .api.routes.target_chat import _check_info_complete
    complete, _ = _check_info_complete(state.get("user_info", {}))
    return "complete" if complete else "incomplete"


async def node_ask_question(state: TargetChatState) -> dict:
    """追问节点 — LLM 流式生成追问。"""
    from .api.routes.target_chat import _check_info_complete, _FIELD_LABELS, _stream_generate_question

    _evt(state, "tool_call", {"tool": "question_gen", "summary": "正在思考要问你什么..."})

    user_info = state.get("user_info", {})
    _, missing = _check_info_complete(user_info)
    next_field = missing[0] if missing else None
    state["asking_field"] = next_field

    # 流式生成追问
    full_text = ""
    async for token in _stream_generate_question(missing, user_info):
        full_text += token
        _evt(state, "text_chunk", {"content": token})

    state["response_text"] = full_text
    state["phase"] = "collecting_info"

    # 快捷操作
    if next_field == "dest_city":
        state["quick_actions"] = ["成都", "厦门", "西安", "长沙", "大理"]
    elif next_field == "origin":
        state["quick_actions"] = ["北京", "上海", "广州", "深圳"]
    elif next_field == "companions":
        state["quick_actions"] = ["1个人", "2个人", "一家三口"]
    else:
        state["quick_actions"] = []

    _evt(state, "quick_actions", {"actions": state["quick_actions"]})
    return state


async def node_research(state: TargetChatState) -> dict:
    """目的地研究节点 — Agent 工具调用。"""
    from .api.routes.target_chat import _agent_research_destination

    user_info = state["user_info"]
    city = user_info["dest_city"]

    _evt(state, "tool_call", {
        "tool": "destination_research",
        "summary": f"正在搜索{city}的旅游特色..."
    })

    tool_calls = await _agent_research_destination(
        city, user_info.get("preferences", [])
    )
    state["tool_results"] = tool_calls
    for tc in tool_calls:
        _evt(state, "tool_result", {"tool": tc["tool"], "result": tc["result"]})

    return state


async def node_collect_pois(state: TargetChatState) -> dict:
    """POI 采集节点。"""
    user_info = state["user_info"]
    city = user_info["dest_city"]

    _evt(state, "tool_call", {
        "tool": "poi_collect",
        "summary": f"正在为{city}采集景点、餐厅、酒店..."
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

    _evt(state, "tool_result", {
        "tool": "poi_collect",
        "result": f"采集完成：{len(pois_result.get('pois', []))}个景点, {len(pois_result.get('hotels', []))}家酒店"
    })
    return state


async def node_rag_search(state: TargetChatState) -> dict:
    """RAG 语义检索节点 — 用偏好搜索匹配 POI。"""
    user_info = state["user_info"]
    preferences = user_info.get("preferences", [])
    city = user_info["dest_city"]
    pois_result = state.get("pois_result", {})
    all_pois = pois_result.get("pois", []) + pois_result.get("hotels", [])

    # 索引到向量库
    existing_count = await asyncio.to_thread(count_pois, city)
    if existing_count < len(all_pois) * 0.5:
        await asyncio.to_thread(index_pois, all_pois, city)

    # 语义搜索
    if preferences:
        rag_query = f"{city} {' '.join(preferences)} 旅行推荐"
        _evt(state, "tool_call", {
            "tool": "rag_search",
            "summary": f"正在语义检索：{rag_query}..."
        })

        rag_results = await asyncio.to_thread(search_pois, rag_query, city, 15)
        rag_ids = {r["id"] for r in rag_results[:10]}

        # 加权提升 RAG 匹配的 POI
        for poi in all_pois:
            if poi["id"] in rag_ids:
                poi["score"] = poi.get("score", 0) + 1.5

        _evt(state, "tool_result", {
            "tool": "rag_search",
            "result": f"语义匹配 {len(rag_ids)} 个高相关 POI：{', '.join(r['name'] for r in rag_results[:5])}"
        })

    return state


async def node_generate_itinerary(state: TargetChatState) -> dict:
    """行程生成节点。"""
    user_info = state["user_info"]
    pois_result = state.get("pois_result", {})

    _evt(state, "tool_call", {"tool": "itinerary_gen", "summary": "正在生成最优行程..."})

    initial_itinerary = pois_result.get("initial_itinerary", [])
    from .api.routes.target_chat import _enrich_itinerary
    itinerary = _enrich_itinerary(
        initial_itinerary,
        pois_result.get("pois", []),
        pois_result.get("hotels", []),
    )
    state["itinerary"] = itinerary
    state["phase"] = "generating_itinerary"

    _evt(state, "tool_result", {"tool": "itinerary_gen", "result": "行程生成完成"})

    # P0: 行程完成后沉淀记忆（异步，不阻塞）
    try:
        trip_data = {
            "city": user_info.get("dest_city"),
            "days": user_info.get("days"),
            "budget": user_info.get("budget"),
            "companions": user_info.get("companions"),
            "preferences": user_info.get("preferences", []),
            "itinerary_summary": f"{user_info.get('dest_city')} {user_info.get('days')}天行程",
        }
        await asyncio.to_thread(
            extract_and_save, state.get("session_id", "default"), trip_data
        )
        logger.info("记忆沉淀完成：%s", state.get("session_id"))
    except Exception as e:
        logger.warning("记忆沉淀失败（不影响行程）：%s", e)

    # P5: 行程质量评估
    eval_result = {}
    try:
        from .evaluation import evaluate_itinerary
        eval_result = evaluate_itinerary(itinerary, user_info, pois_result.get("pois", []))
        logger.info("行程评分：%s", eval_result)
        _evt(state, "tool_result", {
            "tool": "quality_eval",
            "result": f"质量评分：{eval_result['overall']:.0%} — {eval_result['summary']}"
        })
    except Exception as e:
        logger.warning("行程评估失败：%s", e)

    # 生成结果摘要
    dest = user_info["dest_city"]
    days = user_info["days"]
    n_items = len(initial_itinerary[0]["items"]) if initial_itinerary else 0
    result_text = (
        f"✨ {dest} {days}天行程出来了！\n\n"
        f"我帮你搜了{dest}的特色，安排了 {n_items} 个站点/天。\n\n"
        "你可以：\n• 查看详细行程\n• 调整景点\n• 导出保存"
    )

    # P4: 季节感知提示
    from .api.routes.target_chat import _get_season_tip
    month = user_info.get("month", 0)
    if not month:
        from datetime import datetime
        month = datetime.now().month
    season_tip = _get_season_tip(dest, month)
    if season_tip:
        result_text += f"\n\n🌤 {season_tip}"

    # P5: 评分摘要
    if eval_result.get("overall"):
        result_text += f"\n\n📊 行程质量：{eval_result['overall']:.0%} — {eval_result.get('summary', '')}"

    state["response_text"] = result_text
    state["quick_actions"] = ["查看详细行程", "调整景点", "重新规划"]

    _evt(state, "text_chunk", {"content": result_text})
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

【输出格式】严格返回 JSON 数组（与原格式相同）：
[
  {{"day": 1, "items": [...], "total_cost": 0}}
]
只输出 JSON，不要解释。"""


async def node_adjust_itinerary(state: TargetChatState) -> dict:
    """P1: LLM 理解用户调整指令并修改行程。"""
    itinerary = state.get("itinerary", [])
    message = state.get("message", "")
    user_info = state.get("user_info", {})

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

        # 提取 JSON 数组
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("LLM 未返回有效 JSON")

        new_itinerary = json.loads(raw[start:end + 1])

        if not new_itinerary:
            # 用户要求重新生成
            state["response_text"] = "好的，我重新帮你规划～"
            state["phase"] = "collecting_info"
            state["user_info"] = {k: v for k, v in user_info.items() if k in ["dest_city"]}
            state["itinerary"] = None
            _evt(state, "text_chunk", {"content": "好的，重新规划！你还想去哪些地方？"})
            return state

        state["itinerary"] = new_itinerary

        # 生成调整摘要
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
        state["response_text"] = f"抱歉，没能理解你的意思。可以试试：\n• 告诉我去掉哪个景点\n• 告诉我加什么类型的景点"
        state["quick_actions"] = ["重新生成", "确认行程"]
        _evt(state, "text_chunk", {"content": state["response_text"]})
        _evt(state, "quick_actions", {"actions": state["quick_actions"]})

    return state


# ─── 构建图 ──────────────────────────────────────────

def build_target_graph() -> StateGraph:
    """构建定向定制对话图。"""
    graph = StateGraph(TargetChatState)

    # 添加节点
    graph.add_node("greeting", node_greeting)
    graph.add_node("extract_info", node_extract_info)
    graph.add_node("ask_question", node_ask_question)
    graph.add_node("research", node_research)
    graph.add_node("collect_pois", node_collect_pois)
    graph.add_node("rag_search", node_rag_search)
    graph.add_node("generate_itinerary", node_generate_itinerary)

    # 边：START → greeting
    graph.add_edge(START, "greeting")

    # greeting → extract_info（用户首次输入后）
    graph.add_edge("greeting", "extract_info")

    # extract_info → 条件判断
    graph.add_conditional_edges(
        "extract_info",
        edge_check_info,
        {
            "complete": "research",
            "incomplete": "ask_question",
        },
    )

    # ask_question → END（等用户回复）
    graph.add_edge("ask_question", END)

    # research → collect_pois → rag_search → generate_itinerary → END
    graph.add_edge("research", "collect_pois")
    graph.add_edge("collect_pois", "rag_search")
    graph.add_edge("rag_search", "generate_itinerary")
    graph.add_edge("generate_itinerary", END)

    return graph


# 编译后的图实例（带内存检查点）
def create_compiled_graph():
    """创建编译后的图实例。"""
    graph = build_target_graph()
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# 全局图实例
_compiled_graph = None

def get_graph():
    """获取编译后的图实例（单例）。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = create_compiled_graph()
    return _compiled_graph
