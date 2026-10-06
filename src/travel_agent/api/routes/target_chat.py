"""定向定制对话 API — Agent 驱动的需求采集 + 行程生成。

与灵感漫游的区别：
  - 用户已知目的地，不需要城市推荐
  - 开头 Agent 主动抓取需求（可调用工具搜索目的地信息）
  - 信息采集完成后直接生成 POI + 行程
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional, Literal, AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...llm import get_llm, stream_llm
from ...agents.poi_collector import collect_pois_v2
from ...agents.itinerary_planner import generate_initial_itinerary
from ...memory.poi_vector_store import index_pois, search_pois, count_pois

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── 会话存储 ────────────────────────────────────────
_sessions: dict[str, dict] = {}


def _get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "created_at": datetime.now().isoformat(),
            "phase": "greeting",
            "messages": [],
            "user_info": {},
            "itinerary": None,
            "asking_field": None,
            "tool_results": [],
        }
    return _sessions[session_id]


# ─── 请求/响应模型 ───────────────────────────────────

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class TargetChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ItineraryItem(BaseModel):
    poi_id: str
    period: Literal["morning", "noon", "afternoon", "evening"] = "morning"
    name: str = ""
    poi_type: str = "attraction"
    cost: float = 0.0
    duration: int = 90
    lat: float = 0.0
    lng: float = 0.0
    image_url: str = ""


class ItineraryDay(BaseModel):
    day: int
    items: list[ItineraryItem] = []
    total_cost: float = 0.0


class TargetChatResponse(BaseModel):
    session_id: str
    text: str
    phase: str
    itinerary: Optional[list[ItineraryDay]] = None
    quick_actions: list[str] = []
    user_info: Optional[dict] = None
    tool_calls: Optional[list[dict]] = None
    dest_city: Optional[str] = None


# ─── 正则降级提取 ────────────────────────────────────

_COMMON_CITIES = [
    "北京", "上海", "广州", "深圳", "成都", "杭州", "西安", "重庆",
    "厦门", "大理", "丽江", "三亚", "桂林", "长沙", "武汉", "南京",
    "青岛", "苏州", "昆明", "哈尔滨", "东莞", "佛山", "珠海", "天津",
    "郑州", "济南", "沈阳", "大连", "长春", "合肥", "福州", "南昌",
    "贵阳", "兰州", "乌鲁木齐", "拉萨", "呼和浩特", "银川", "西宁",
    "温州", "宁波", "无锡", "常州", "烟台", "潍坊", "泉州", "汕头",
    "潮州", "漳州", "乐山", "峨眉山", "九寨沟",
]

_PREF_MAP = {
    "美食": "美食", "吃": "美食", "火锅": "美食", "小吃": "美食",
    "自然": "自然", "山水": "自然", "风景": "自然", "海": "自然",
    "历史": "历史", "古迹": "历史", "文化": "历史", "博物馆": "历史",
    "购物": "购物", "买": "购物", "商场": "购物",
    "摄影": "摄影", "拍照": "摄影", "打卡": "摄影",
    "冒险": "冒险", "户外": "冒险", "徒步": "冒险",
    "休闲": "休闲", "度假": "休闲", "放松": "休闲",
}

_INTENSITY_MAP = {
    "躺": "边走边躺", "轻松": "边走边躺", "休闲": "边走边躺", "慢": "边走边躺",
    "正常": "莫名其妙地玩", "普通": "莫名其妙地玩", "一般": "莫名其妙地玩",
    "特种兵": "死了都要逛", "累": "死了都要逛", "满": "死了都要逛", "紧凑": "死了都要逛",
}

_FIELD_LABELS = {
    "dest_city": "目的地城市名",
    "origin": "出发地城市名",
    "budget": "总预算数字（元）",
    "days": "出行天数数字",
    "companions": "出行人数数字",
    "month": "出行月份数字（1-12）",
}

# ─── 季节感知 ─────────────────────────────────────

_SEASON_TIPS = {
    "spring": "{city}春天正是好时候！樱花/油菜花/古镇漫步，记得带薄外套～",
    "summer": "{city}夏天比较热，建议安排室内景点+夜间活动，带好防晒～",
    "autumn": "{city}秋天太棒了！红叶/桂花/凉爽天气，最适合户外玩～",
    "winter": "{city}冬天偏冷，可以安排温泉/火锅/博物馆，记得带厚衣服～",
}

def _get_season_tip(city: str, month: int) -> str:
    """根据月份返回季节提示。"""
    if not month or month < 1 or month > 12:
        return ""
    if month in [3, 4, 5]:
        season = "spring"
    elif month in [6, 7, 8]:
        season = "summer"
    elif month in [9, 10, 11]:
        season = "autumn"
    else:
        season = "winter"
    return _SEASON_TIPS[season].format(city=city)


def _regex_extract(message: str, existing: dict, asking_field: str | None = None) -> dict:
    """正则提取用户信息。"""
    msg = message.strip()
    if not msg:
        return existing

    clean = msg.strip().rstrip("。！？!?,，")

    # 纯数字 → 当前追问字段
    if asking_field and re.fullmatch(r"\d{1,6}", clean):
        n = int(clean)
        if asking_field == "days" and 1 <= n <= 30:
            existing["days"] = n
        elif asking_field == "companions" and 1 <= n <= 30:
            existing["companions"] = n
        elif asking_field == "budget" and 100 <= n <= 999999:
            existing["budget"] = n

    # 目的地
    if "dest_city" not in existing or not existing["dest_city"]:
        for city in _COMMON_CITIES:
            if city in msg:
                existing["dest_city"] = city
                break

    # 出发地
    if "origin" not in existing or not existing["origin"]:
        m = re.search(r"(?:从|自)\s*([\u4e00-\u9fa5]{2,4})", msg)
        if m:
            c = m.group(1)
            for city in _COMMON_CITIES:
                if city == c or city in c or c in city:
                    existing["origin"] = city
                    break

    # 预算
    if "budget" not in existing or not existing["budget"]:
        m = re.search(r"(\d{2,5})\s*(?:到|-|~|至)\s*(\d{2,5})", msg)
        if m:
            existing["budget"] = int(m.group(2))
        else:
            m = re.search(r"(?:预算|准备|花|大概|约)?\s*(\d{3,6})\s*(?:元|块|钱)?", msg)
            if m:
                existing["budget"] = int(m.group(1))

    # 天数
    if "days" not in existing or not existing["days"]:
        m = re.search(r"(?:玩|待|呆|旅游)?\s*(\d{1,2})\s*天", msg)
        if m:
            existing["days"] = int(m.group(1))

    # 人数
    if "companions" not in existing or not existing["companions"]:
        m = re.search(r"(\d{1,2})\s*(?:人|个)", msg)
        if m:
            existing["companions"] = int(m.group(1))
        elif re.search(r"独自|一个人|solo", msg):
            existing["companions"] = 1
        elif re.search(r"情侣|两人|两个人|俩", msg):
            existing["companions"] = 2
        elif re.search(r"一家三口|三人|三个", msg):
            existing["companions"] = 3

    # 偏好
    if "preferences" not in existing:
        existing["preferences"] = []
    for kw, tag in _PREF_MAP.items():
        if kw in msg and tag not in existing["preferences"]:
            existing["preferences"].append(tag)

    # 强度
    if "intensity" not in existing or not existing["intensity"]:
        for kw, intensity in _INTENSITY_MAP.items():
            if kw in msg:
                existing["intensity"] = intensity
                break

    # 月份
    if "month" not in existing or not existing["month"]:
        m = re.search(r"(\d{1,2})\s*月", msg)
        if m:
            month = int(m.group(1))
            if 1 <= month <= 12:
                existing["month"] = month
        else:
            # 中文月份
            cn_month = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
            for cn, num in cn_month.items():
                if cn + "月" in msg:
                    existing["month"] = num
                    break
            # 季节关键词
            if "month" not in existing:
                if "春天" in msg or "春季" in msg or "清明" in msg:
                    existing["month"] = 4
                elif "夏天" in msg or "暑假" in msg or "暑期" in msg:
                    existing["month"] = 7
                elif "秋天" in msg or "秋季" in msg or "国庆" in msg:
                    existing["month"] = 10
                elif "冬天" in msg or "冬季" in msg or "春节" in msg or "寒假" in msg:
                    existing["month"] = 1

    return existing


# ─── LLM 提取 ────────────────────────────────────────

async def _extract_user_info(message: str, existing: dict, asking_field: str | None = None) -> dict:
    result = _regex_extract(message, dict(existing), asking_field)
    llm = get_llm(json_mode=True)

    context_hint = ""
    if asking_field:
        label = _FIELD_LABELS.get(asking_field, asking_field)
        context_hint = f"\n【上下文】上一轮正在追问【{label}】。纯数字优先理解为对【{asking_field}】的回复。\n"

    prompt = f"""你是旅行助手的信息提取器。从用户消息提取关键信息，返回 JSON。
{context_hint}
【已有信息】{json.dumps(existing, ensure_ascii=False)}
【用户消息】{message}

【提取字段】
- dest_city: 目的地
- origin: 出发地
- budget: 预算（元，区间取上限）
- days: 天数
- companions: 人数（"一个人"→1，"情侣"→2）
- preferences: 偏好 [美食/自然/历史/购物/摄影/冒险/休闲]
- intensity: "边走边躺" / "莫名其妙地玩" / "死了都要逛"

【规则】
1. 只返回 NEW 信息
2. 无新信息返回 {{}}
3. 只输出 JSON

【示例】
"想去成都3天吃火锅" → {{"dest_city":"成都","days":3,"preferences":["美食"]}}
"从东莞出发，5000预算" → {{"origin":"东莞","budget":5000}}
"""

    try:
        resp = await asyncio.to_thread(llm.invoke, prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        raw = re.sub(r"^```json\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        data = json.loads(raw)
        for k, v in data.items():
            if v is not None and v != "" and v != []:
                result[k] = v
        logger.info("LLM 提取：asking=%s msg=%r → %s", asking_field, message, data)
    except Exception as e:
        logger.warning("LLM 提取失败：%s", e)

    return result


# ─── Agent 工具调用 ──────────────────────────────────

async def _agent_research_destination(dest_city: str, preferences: list[str]) -> list[dict]:
    """Agent 调用工具搜索目的地信息。"""
    tool_results = []

    # 工具1：搜索目的地特色
    try:
        llm = get_llm()
        pref_str = "、".join(preferences) if preferences else "综合"
        resp = await asyncio.to_thread(
            llm.invoke,
            f"你是旅行顾问。简要列出{dest_city}最值得体验的3个特色和2个注意事项，"
            f"用户偏好：{pref_str}。用 3-5 句话回答，口语化。"
        )
        text = (resp.content if hasattr(resp, "content") else str(resp)).strip()
        tool_results.append({
            "tool": "destination_research",
            "summary": f"搜索了{dest_city}的旅游特色",
            "result": text[:200],
        })
    except Exception as e:
        logger.warning("目的地研究失败：%s", e)

    return tool_results


# ─── 追问 ────────────────────────────────────────────

async def _generate_question(missing_fields: list[str], user_info: dict) -> str:
    """生成追问（非流式，兼容旧调用）。"""
    tokens = []
    async for token in _stream_generate_question(missing_fields, user_info):
        tokens.append(token)
    return "".join(tokens)


async def _stream_generate_question(
    missing_fields: list[str], user_info: dict
) -> AsyncGenerator[str, None]:
    """流式生成追问 — 逐 token yield LLM 输出。"""
    if not missing_fields:
        yield "信息差不多了，让我帮你规划行程～"
        return

    next_field = missing_fields[0]

    try:
        known = {k: v for k, v in user_info.items() if v and k != "_memory_context"}
        memory_hint = ""
        if user_info.get("_memory_context"):
            memory_hint = f"\n【历史偏好】{user_info['_memory_context'][:200]}"
        prompt = f"""你是旅行助手，正在帮用户规划去{user_info.get('dest_city', '目的地')}的行程。

【已知】{json.dumps(known, ensure_ascii=False)}{memory_hint}
【还差】{_FIELD_LABELS.get(next_field, next_field)}

用一句自然、口语化的话追问，规则：
- 不超过 25 字
- 像朋友聊天
- 如果有历史偏好，可以简短提及“记得你上次喜欢XX”
- 如果已知信息较多，先简短确认再追问
- 只输出追问本身，不要引号、不要解释
"""
        collected = ""
        async for token in stream_llm(prompt):
            collected += token
            yield token
        clean = collected.strip().strip("\"'「」『』\n ")
        if len(clean) < 3:
            templates = {
                "dest_city": "你想去哪个城市？",
                "origin": "你从哪个城市出发？",
                "budget": "预算大概多少？",
                "days": "计划玩几天？",
                "companions": "几个人一起？",
            }
            fallback = templates.get(next_field, "还有什么想告诉我的？")
            if not collected:
                yield fallback
    except Exception as e:
        logger.debug("LLM 追问失败：%s", e)
        templates = {
            "dest_city": "你想去哪个城市？",
            "origin": "你从哪个城市出发？",
            "budget": "预算大概多少？",
            "days": "计划玩几天？",
            "companions": "几个人一起？",
        }
        yield templates.get(next_field, "还有什么想告诉我的？")


def _check_info_complete(user_info: dict) -> tuple[bool, list[str]]:
    required = ["dest_city", "budget", "days", "companions"]
    missing = [f for f in required if f not in user_info or not user_info[f]]
    return len(missing) == 0, missing


# ─── 行程富化 ────────────────────────────────────────

def _enrich_itinerary(initial: list[dict], pois: list[dict], hotels: list[dict]) -> list[dict]:
    poi_map: dict[str, dict] = {p["id"]: p for p in (pois + hotels)}
    result: list[dict] = []
    for day_schedule in initial:
        day_items: list[dict] = []
        total_cost = 0.0
        for entry in day_schedule.get("items", []):
            poi_id = entry.get("poi_id", "")
            poi = poi_map.get(poi_id, {})
            cost = float(poi.get("cost", 0) or 0)
            total_cost += cost
            day_items.append({
                "poi_id": poi_id,
                "period": entry.get("period", "morning"),
                "name": poi.get("name", ""),
                "poi_type": poi.get("poi_type", "attraction"),
                "cost": cost,
                "duration": int(poi.get("duration", 90) or 90),
                "lat": float(poi.get("lat", 0) or 0),
                "lng": float(poi.get("lng", 0) or 0),
                "image_url": poi.get("image_url", ""),
            })
        # 第一天加上酒店住宿费用
        if day_schedule.get("day") == 1 and hotels:
            hotel = hotels[0]
            hotel_cost = float(hotel.get("total_accommodation_cost", 0) or hotel.get("single_night_price", 0) * len(initial))
            total_cost += hotel_cost
        result.append({
            "day": day_schedule.get("day", 0),
            "items": day_items,
            "total_cost": total_cost,
        })
    return result


# ─── 核心对话逻辑 ────────────────────────────────────

@router.post("/chat", response_model=TargetChatResponse)
async def target_chat(req: TargetChatRequest):
    session_id = req.session_id or str(uuid.uuid4())[:8]
    session = _get_session(session_id)

    if req.message and req.message.strip():
        session["messages"].append({"role": "user", "content": req.message})

    phase = session["phase"]
    user_info = session["user_info"]
    asking_field = session.get("asking_field")

    response_text = ""
    itinerary_data = None
    quick_actions = []
    tool_calls = None

    try:
        if phase == "greeting":
            # Agent 开场：主动引导用户说出需求
            response_text = (
                "你好呀～ 告诉我你的旅行想法，我来帮你规划 ✨\n"
                "想去哪里、玩几天、几个人、大概预算，说个大概就行～\n"
                "比如：想去成都吃火锅，3天，2个人，预算5000"
            )
            session["phase"] = "collecting_info"
            quick_actions = ["想去成都", "想去海边", "想看历史古迹"]

        elif phase == "collecting_info":
            user_info = await _extract_user_info(req.message, user_info, asking_field)
            session["user_info"] = user_info

            complete, missing = _check_info_complete(user_info)

            if complete:
                session["phase"] = "researching"
                session["asking_field"] = None

                # Agent 工具调用：研究目的地
                tool_calls = await _agent_research_destination(
                    user_info["dest_city"],
                    user_info.get("preferences", []),
                )
                session["tool_results"] = tool_calls

                # 直接进入 POI 采集
                session["phase"] = "generating_itinerary"

                pois_result = await asyncio.to_thread(
                    collect_pois_v2,
                    city=user_info["dest_city"],
                    budget=int(user_info["budget"]),
                    companions=int(user_info["companions"]),
                    days=int(user_info["days"]),
                    intensity=user_info.get("intensity", "莫名其妙地玩"),
                    preferences=user_info.get("preferences", []),
                )

                initial_itinerary = pois_result.get("initial_itinerary", [])
                itinerary = _enrich_itinerary(
                    initial_itinerary,
                    pois_result.get("pois", []),
                    pois_result.get("hotels", []),
                )
                session["itinerary"] = itinerary
                itinerary_data = itinerary

                dest = user_info["dest_city"]
                response_text = (
                    f"✨ {dest} {user_info['days']}天行程出来了！\n\n"
                    f"我帮你搜了{dest}的特色，安排了 {len(initial_itinerary[0]['items']) if initial_itinerary else 0} 个站点/天。\n\n"
                    f"你可以：\n• 查看详细行程\n• 调整景点\n• 导出保存"
                )
                quick_actions = ["查看详细行程", "调整景点", "重新规划"]
            else:
                response_text = await _generate_question(missing, user_info)
                next_field = missing[0] if missing else None
                session["asking_field"] = next_field

                if next_field == "dest_city":
                    quick_actions = ["成都", "厦门", "西安", "长沙", "大理"]
                elif next_field == "origin":
                    quick_actions = ["北京", "上海", "广州", "深圳"]
                elif next_field == "companions":
                    quick_actions = ["1个人", "2个人", "一家三口"]
                else:
                    quick_actions = []

        elif phase == "generating_itinerary":
            if "详细" in req.message or "查看" in req.message:
                response_text = "这是详细行程：\n\n"
                if session["itinerary"]:
                    period_map = {"morning": "早上", "noon": "中午", "afternoon": "下午", "evening": "晚上"}
                    for day in session["itinerary"]:
                        response_text += f"**第{day['day']}天**\n"
                        for item in day.get("items", []):
                            n = item.get("name") or item.get("poi_id", "未知")
                            p = item.get("period", "")
                            response_text += f"  {period_map.get(p, '')}: {n}\n"
                        response_text += "\n"
                quick_actions = ["调整景点", "确认行程", "重新开始"]
            elif "调整" in req.message:
                response_text = "可以这样调整：\n• 告诉我去掉哪个点\n• 告诉我加什么类型的点\n• 或者我重新生成一版"
                quick_actions = ["重新生成", "换个城市", "确认行程"]
            elif "确认" in req.message or "导出" in req.message:
                response_text = "行程已确认！可以截图保存 ✨"
                quick_actions = ["重新开始", "换个目的地"]
            else:
                response_text = "还想调整什么？或者我们重新开始～"
                quick_actions = ["查看详细行程", "重新开始"]

        else:
            response_text = "我们重新开始吧！你想去哪玩？"
            session["phase"] = "greeting"
            session["user_info"] = {}
            session["asking_field"] = None

    except Exception as e:
        logger.exception("对话处理失败")
        response_text = f"抱歉，出了点小问题：{str(e)}\n请重试～"

    session["messages"].append({"role": "assistant", "content": response_text})
    if len(session["messages"]) > 20:
        session["messages"] = session["messages"][-20:]

    return TargetChatResponse(
        session_id=session_id,
        text=response_text,
        phase=session["phase"],
        itinerary=itinerary_data,
        quick_actions=quick_actions,
        user_info=session["user_info"],
        tool_calls=tool_calls,
        dest_city=session["user_info"].get("dest_city"),
    )


@router.get("/session/{session_id}")
async def get_target_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return session


# ─── SSE 流式对话 ────────────────────────────────────

def _sse_event(event_type: str, data: dict) -> str:
    """构造 SSE 事件。"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_chat(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """流式对话生成器 — LangGraph 图驱动。"""
    session = _get_session(session_id)

    if message and message.strip():
        session["messages"].append({"role": "user", "content": message})

    phase = session["phase"]
    yield _sse_event("session", {"session_id": session_id})

    try:
        # ── 构造图初始状态 ──
        from ...target_graph import (
            node_greeting, node_extract_info, node_ask_question,
            node_research, node_collect_pois, node_rag_search,
            node_generate_itinerary, node_adjust_itinerary,
        )

        graph_state = {
            "session_id": session_id,
            "phase": phase,
            "message": message,
            "user_info": dict(session.get("user_info", {})),
            "asking_field": session.get("asking_field"),
            "itinerary": session.get("itinerary"),
            "tool_results": [],
            "extracted": {},
            "question_text": "",
            "quick_actions": [],
            "response_text": "",
            "pois_result": {},
            "events": [],
            "error": None,
            "messages_history": session.get("messages", [])[-10:],  # P6: 最近 10 条对话历史
        }

        # ── 根据当前 phase 执行图节点序列 ──
        if phase == "greeting":
            # START → greeting → END
            graph_state = await node_greeting(graph_state)
            session["phase"] = "collecting_info"

        elif phase == "collecting_info":
            # extract_info → check → (complete ? research→collect→rag→itinerary : ask)
            graph_state = await node_extract_info(graph_state)
            session["user_info"] = graph_state["user_info"]

            complete, missing = _check_info_complete(graph_state["user_info"])

            if complete:
                session["phase"] = "generating_itinerary"
                session["asking_field"] = None
                graph_state = await node_research(graph_state)
                session["tool_results"] = graph_state["tool_results"]
                graph_state = await node_collect_pois(graph_state)
                graph_state = await node_rag_search(graph_state)
                graph_state = await node_generate_itinerary(graph_state)
                session["itinerary"] = graph_state["itinerary"]
            else:
                graph_state = await node_ask_question(graph_state)
                session["asking_field"] = graph_state["asking_field"]

        elif phase == "generating_itinerary":
            # P1: 行程调整阶段 — LLM 智能理解调整指令
            if "详细" in message or "查看" in message:
                response_text = "这是详细行程：\n\n"
                if session["itinerary"]:
                    period_map = {"morning": "早上", "noon": "中午", "afternoon": "下午", "evening": "晚上"}
                    for day in session["itinerary"]:
                        response_text += f"**第{day['day']}天**\n"
                        for item in day.get("items", []):
                            n = item.get("name") or item.get("poi_id", "未知")
                            p = item.get("period", "")
                            response_text += f"  {period_map.get(p, '')}: {n}\n"
                        response_text += "\n"
                for i in range(0, len(response_text), 3):
                    graph_state["events"].append({"event": "text_chunk", "data": {"content": response_text[i:i+3]}})
                graph_state["events"].append({"event": "quick_actions", "data": {"actions": ["调整景点", "确认行程", "重新开始"]}})
            elif "确认" in message or "导出" in message:
                response_text = "行程已确认！可以截图保存 ✨"
                for i in range(0, len(response_text), 3):
                    graph_state["events"].append({"event": "text_chunk", "data": {"content": response_text[i:i+3]}})
                graph_state["events"].append({"event": "quick_actions", "data": {"actions": ["重新开始", "换个目的地"]}})
            else:
                # P1: 调用 LLM 智能调整行程
                graph_state = await node_adjust_itinerary(graph_state)
                if graph_state.get("itinerary"):
                    session["itinerary"] = graph_state["itinerary"]
                response_text = graph_state.get("response_text", "")

        else:
            response_text = "我们重新开始吧！你想去哪玩？"
            session["phase"] = "greeting"
            session["user_info"] = {}
            session["asking_field"] = None
            for i in range(0, len(response_text), 3):
                graph_state["events"].append({"event": "text_chunk", "data": {"content": response_text[i:i+3]}})

        # ── 消费图事件队列，输出 SSE ──
        for evt in graph_state["events"]:
            yield _sse_event(evt["event"], evt["data"])

        yield _sse_event("done", {"phase": graph_state.get("phase", phase)})

    except Exception as e:
        logger.exception("流式对话失败")
        err_text = f"抱歉，出了点小问题：{str(e)}\n请重试～"
        yield _sse_event("text_chunk", {"content": err_text})
        yield _sse_event("done", {"phase": phase})

    session["messages"].append({"role": "assistant", "content": message})
    if len(session["messages"]) > 20:
        session["messages"] = session["messages"][-20:]


@router.post("/chat/stream")
async def target_chat_stream(req: TargetChatRequest):
    """SSE 流式对话端点。"""
    session_id = req.session_id or str(uuid.uuid4())[:8]
    return StreamingResponse(
        _stream_chat(session_id, req.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── P8: 用户反馈 API ─────────────────────────────────

class FeedbackRequest(BaseModel):
    session_id: str
    poi_name: str
    city: str = ""
    feedback: Literal["liked", "disliked"]
    reason: str = ""


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """用户反馈：点赞/踩某个 POI，写入记忆。"""
    from ...memory.memory_agent import mark_liked, mark_disliked

    user_id = req.session_id
    if req.feedback == "liked":
        count = mark_liked(user_id, req.poi_name, req.city, req.reason)
    else:
        count = mark_disliked(user_id, req.poi_name, req.city, req.reason)

    return {
        "status": "ok",
        "feedback": req.feedback,
        "poi": req.poi_name,
        "saved": count,
    }
