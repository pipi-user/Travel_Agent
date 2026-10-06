"""灵感漫游对话 API — 像聊天一样规划旅行。

统一入口 /api/inspire/chat，LLM + 正则降级提取用户意图。
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

from ...llm import get_llm
from ...agents.destination import recommend_cities
from ...agents.poi_collector import collect_pois_v2
from ...agents.itinerary_planner import generate_initial_itinerary

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
            "cities": [],
            "selected_city": None,
            "itinerary": None,
            "asking_field": None,
            "user_id": "demo",
            "user_profile": {},
            "memory_block": "",
        }
    return _sessions[session_id]


# ─── 请求/响应模型 ───────────────────────────────────

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class CityCard(BaseModel):
    city: str
    score: float
    reason: str
    tags: list[str] = []
    daily_cost: int = 0
    intro: str = ""
    image_url: str = ""


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


class ChatResponse(BaseModel):
    session_id: str
    text: str
    phase: str
    cities: Optional[list[CityCard]] = None
    itinerary: Optional[list[ItineraryDay]] = None
    quick_actions: list[str] = []
    user_info: Optional[dict] = None
    selected_city: Optional[str] = None


class AdjustRequest(BaseModel):
    city: str
    message: str
    itinerary: list[dict]
    pois: list[dict]


class AdjustResponse(BaseModel):
    itinerary: list[dict]
    text: str
    success: bool = True


# ─── 行程富化 ────────────────────────────────────────

def _enrich_itinerary(
    initial: list[dict],
    pois: list[dict],
    hotels: list[dict],
) -> list[dict]:
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


# ─── 正则降级提取 ────────────────────────────────────

_COMMON_CITIES = [
    "北京", "上海", "广州", "深圳", "成都", "杭州", "西安", "重庆",
    "厦门", "大理", "丽江", "三亚", "桂林", "长沙", "武汉", "南京",
    "青岛", "苏州", "昆明", "哈尔滨", "东莞", "佛山", "珠海", "天津",
    "郑州", "济南", "沈阳", "大连", "长春", "合肥", "福州", "南昌",
    "贵阳", "兰州", "乌鲁木齐", "拉萨", "呼和浩特", "银川", "西宁",
    "温州", "宁波", "无锡", "常州", "烟台", "潍坊", "泉州", "汕头",
]

_INTENSITY_MAP = {
    "躺": "边走边躺", "轻松": "边走边躺", "休闲": "边走边躺", "慢": "边走边躺",
    "正常": "莫名其妙地玩", "普通": "莫名其妙地玩", "一般": "莫名其妙地玩",
    "特种兵": "死了都要逛", "累": "死了都要逛", "满": "死了都要逛", "紧凑": "死了都要逛",
}

_PREF_MAP = {
    "美食": "美食", "吃": "美食", "火锅": "美食", "小吃": "美食",
    "自然": "自然", "山水": "自然", "风景": "自然", "海": "自然",
    "历史": "历史", "古迹": "历史", "文化": "历史", "博物馆": "历史",
    "购物": "购物", "买": "购物", "商场": "购物",
    "摄影": "摄影", "拍照": "摄影", "打卡": "摄影",
    "冒险": "冒险", "户外": "冒险", "徒步": "冒险",
    "休闲": "休闲", "度假": "休闲", "放松": "休闲",
}

_FIELD_LABELS = {
    "origin": "出发地城市名",
    "budget": "总预算数字（元）",
    "days": "出行天数数字",
    "companions": "出行人数数字",
}


def _regex_extract(message: str, existing: dict, asking_field: str | None = None) -> dict:
    msg = message.strip()
    if not msg:
        return existing

    clean = msg.strip().rstrip("。！？!?,，")

    if asking_field and re.fullmatch(r"\d{1,6}", clean):
        n = int(clean)
        if asking_field == "days" and 1 <= n <= 30:
            existing["days"] = n
        elif asking_field == "companions" and 1 <= n <= 30:
            existing["companions"] = n
        elif asking_field == "budget" and 100 <= n <= 999999:
            existing["budget"] = n

    if asking_field == "origin" and 2 <= len(clean) <= 4 and "origin" not in existing:
        for city in _COMMON_CITIES:
            if city == clean or city in clean or clean in city:
                existing["origin"] = city
                break
        else:
            existing["origin"] = clean

    if "origin" not in existing or not existing["origin"]:
        # 匹配"从/去/到/前往 + 城市" 或 "城市 + 出发/出发地"
        m = re.search(r"(?:去|从|到|出发|前往)\s*([\u4e00-\u9fa5]{2,4})", msg)
        if not m:
            m = re.search(r"([\u4e00-\u9fa5]{2,4})\s*(?:出发|出发地)", msg)
        if m:
            c = m.group(1)
            for city in _COMMON_CITIES:
                if city in c or c in city:
                    existing["origin"] = city
                    break
        if "origin" not in existing:
            m = re.search(r"([\u4e00-\u9fa5]{2,4})(?:玩|旅游|旅行|吗|吧|呀|！|!|$)", msg)
            if m:
                c = m.group(1)
                for city in _COMMON_CITIES:
                    if city == c or city in c or c in city:
                        existing["origin"] = city
                        break
        if "origin" not in existing and 2 <= len(clean) <= 4:
            for city in _COMMON_CITIES:
                if city == clean or clean in city or city in clean:
                    existing["origin"] = city
                    break

    if "budget" not in existing or not existing["budget"]:
        m = re.search(r"(\d{2,5})\s*(?:到|-|~|至)\s*(\d{2,5})", msg)
        if m:
            existing["budget"] = int(m.group(2))
        else:
            m = re.search(r"(?:预算|准备|花|大概|约)?\s*(\d{3,6})\s*(?:元|块|钱)?", msg)
            if m:
                existing["budget"] = int(m.group(1))

    if "days" not in existing or not existing["days"]:
        # 阿拉伯数字：玩3天 / 3天
        m = re.search(r"(?:玩|待|呆|旅游)?\s*(\d{1,2})\s*天", msg)
        if m:
            existing["days"] = int(m.group(1))
        else:
            # 中文数字：三天 / 玩三天 / 三天两夜
            cn_map = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            m = re.search(r"(?:玩|待|呆|旅游)?\s*([\u4e00-\u9fa5])\s*天", msg)
            if m and m.group(1) in cn_map:
                existing["days"] = cn_map[m.group(1)]

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

    if "preferences" not in existing:
        existing["preferences"] = []
    for kw, tag in _PREF_MAP.items():
        if kw in msg and tag not in existing["preferences"]:
            existing["preferences"].append(tag)

    if "intensity" not in existing or not existing["intensity"]:
        for kw, intensity in _INTENSITY_MAP.items():
            if kw in msg:
                existing["intensity"] = intensity
                break

    return existing


# ─── LLM 提取 ────────────────────────────────────────

async def _extract_user_info(message: str, existing: dict, asking_field: str | None = None) -> dict:
    result = _regex_extract(message, dict(existing), asking_field)
    llm = get_llm(json_mode=True)

    context_hint = ""
    if asking_field:
        label = _FIELD_LABELS.get(asking_field, asking_field)
        context_hint = (
            f"\n【上下文】上一轮助手正在追问【{label}】。"
            f"如果用户回复是纯数字，优先理解为对【{asking_field}】的回复。\n"
        )

    prompt = f"""你是旅行助手的信息提取器。从用户消息提取关键信息，返回 JSON。
{context_hint}
【已有信息】{json.dumps(existing, ensure_ascii=False)}
【用户消息】{message}

【提取字段】
- origin: 出发地
- budget: 预算（元，区间取上限）
- days: 天数
- companions: 人数（"一个人"→1，"情侣"→2）
- preferences: 偏好，可选 [美食/自然/历史/购物/摄影/冒险/休闲]
- intensity: "边走边躺" / "莫名其妙地玩" / "死了都要逛"

【规则】
1. 只返回 NEW 信息
2. 无新信息返回 {{}}
3. 上下文追问时，纯数字直接映射
4. 只输出 JSON

【示例】
上下文问"玩几天"，答"2" → {{"days": 2}}
用户说 "东莞3天预算5000想吃美食" → {{"origin":"东莞","days":3,"budget":5000,"preferences":["美食"]}}
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


# ─── 追问 ────────────────────────────────────────────

async def _generate_question(missing_fields: list[str], user_info: dict) -> str:
    """生成自然的追问。优先 LLM，兜底模板。"""
    if not missing_fields:
        return "信息都齐了，让我帮你看看有哪些城市合适～"

    next_field = missing_fields[0]

    try:
        llm = get_llm()
        known = {k: v for k, v in user_info.items() if v}
        prompt = f"""你是旅行助手，正在和用户聊旅行计划。

【已知】{json.dumps(known, ensure_ascii=False)}
【还差】{_FIELD_LABELS.get(next_field, next_field)}

用一句自然、口语化的话追问，规则：
- 不超过 25 字
- 像朋友聊天，用"你"，不要"您"
- 如果已知信息较多，可以先简短确认（如"好嘞，广州出发"），再追问
- 只输出追问本身，不要引号、不要解释
"""
        resp = await asyncio.to_thread(llm.invoke, prompt)
        text = (resp.content if hasattr(resp, "content") else str(resp)).strip()
        text = text.strip("\"'「」『』\n ")
        if text and 5 <= len(text) <= 50:
            return text
    except Exception as e:
        logger.debug("LLM 追问失败，用兜底：%s", e)

    known_parts = []
    if user_info.get("origin"):
        known_parts.append(f"从{user_info['origin']}出发")
    if user_info.get("days"):
        known_parts.append(f"玩{user_info['days']}天")
    if user_info.get("budget"):
        known_parts.append(f"预算{user_info['budget']}")
    if user_info.get("companions"):
        known_parts.append(f"{user_info['companions']}人")

    ctx = ("好嘞，" + "、".join(known_parts) + "，") if known_parts else ""
    templates = {
        "origin": "你从哪个城市出发呀？",
        "budget": "预算大概多少呢？",
        "days": "计划玩几天？",
        "companions": "几个人一起？",
    }
    return f"{ctx}{templates.get(next_field, '还有其他想说的吗？')}"


def _check_info_complete(user_info: dict) -> tuple[bool, list[str]]:
    required = ["origin", "budget", "days", "companions"]
    missing = [f for f in required if f not in user_info or not user_info[f]]
    return len(missing) == 0, missing


# ─── RAG 精准筛选 POI ───────────────────────────────

def _apply_rag_to_itinerary(
    pois_result: dict,
    user_preferences: list[str],
    city: str,
    days: int,
    intensity: str,
) -> list[dict]:
    """用 RAG 检索，把命中的 POI 提前。返回新的 initial_itinerary。"""
    raw_pois = pois_result.get("pois", [])
    if not raw_pois:
        return pois_result.get("initial_itinerary", [])

    rag_ids: set[str] = set()

    if user_preferences:
        try:
            from ...memory.poi_vector_store import search_pois
            pref_query = " ".join(user_preferences)
            hits = search_pois(pref_query, city, k=50)
            rag_ids = {h["id"] for h in hits}
            logger.info("RAG 命中 %d 条（query=%r）", len(rag_ids), pref_query)
        except Exception as e:
            logger.warning("RAG 检索失败，退回默认排序：%s", e)

    sorted_pois = sorted(
        raw_pois,
        key=lambda p: (
            0 if p["id"] in rag_ids else 1,
            -float(p.get("score", 0) or 0),
        ),
    )

    attractions = [p for p in sorted_pois if p["poi_type"] == "attraction"]
    foods = [p for p in sorted_pois if p["poi_type"] == "food"]

    return generate_initial_itinerary(
        attractions=attractions,
        foods=foods,
        days=days,
        intensity=intensity,
    )


# ─── 核心对话逻辑 ────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def inspire_chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())[:8]
    session = _get_session(session_id)

    # ⭐ 空消息不存（首次触发问候时 message=''）
    if req.message and req.message.strip():
        session["messages"].append({"role": "user", "content": req.message})

    phase = session["phase"]
    user_info = session["user_info"]
    asking_field = session.get("asking_field")

    response_text = ""
    cities_data = None
    itinerary_data = None
    quick_actions = []

    try:
        if phase == "greeting":
            # ⭐ 加载用户记忆
            try:
                from ...memory.memory_agent import retrieve_context
                uid = session.get("user_id", "demo")
                ctx = retrieve_context(uid, "", k=6)
                session["user_profile"] = ctx.get("profile", {})
                session["memory_block"] = ctx.get("prompt_block", "")
                logger.info("加载用户记忆：%s", session["memory_block"][:120])
            except Exception as e:
                logger.warning("加载记忆失败：%s", e)

            profile = session.get("user_profile", {})
            has_memory = any([
                profile.get("allergies"),
                profile.get("fears"),
                profile.get("dietary"),
                profile.get("pace_preference"),
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
                response_text = (
                    f"嗨！又见面啦 🌟\n\n"
                    f"我记得你{hint}。这次想去哪玩？"
                )
            else:
                response_text = (
                    "嗨！我是你的旅行助手 🌟\n\n"
                    "想去哪玩？跟我说说你的出发地、预算、同行人数，天数，我帮你看看有哪些好去处～"
                )

            session["phase"] = "collecting_info"
            quick_actions = ["北京出发", "3天预算5000", "帮我推荐几个城市"]

        elif phase == "collecting_info":
            user_info = await _extract_user_info(req.message, user_info, asking_field)
            session["user_info"] = user_info

            complete, missing = _check_info_complete(user_info)

            if complete:
                session["phase"] = "recommending"
                session["asking_field"] = None

                # ⭐ 从 session 读用户画像，合入 intensity
                profile = session.get("user_profile", {})
                if not user_info.get("intensity") and profile.get("pace_preference"):
                    pace = profile["pace_preference"]
                    if pace in ["轻松", "休闲", "慢"]:
                        user_info["intensity"] = "边走边躺"
                    elif pace in ["紧凑", "特种兵"]:
                        user_info["intensity"] = "死了都要逛"
                    logger.info("画像节奏 %s → intensity=%s", pace, user_info.get("intensity"))

                cities = await asyncio.to_thread(
                    recommend_cities,
                    origin=user_info["origin"],
                    budget=int(user_info["budget"]),
                    companions=int(user_info["companions"]),
                    days=int(user_info["days"]),
                    intensity=user_info.get("intensity", "莫名其妙地玩"),
                    preferences=user_info.get("preferences", []),
                )

                session["cities"] = cities
                cities_data = cities

                response_text = f"根据你的需求，我挑了 {len(cities)} 个城市：\n\n"
                response_text += "👇 点卡片看详情，或者直接告诉我你想去哪～"
                quick_actions = [c["city"] for c in cities[:3]]
            else:
                response_text = await _generate_question(missing, user_info)
                next_field = missing[0] if missing else None
                session["asking_field"] = next_field

                if next_field == "origin":
                    quick_actions = ["北京", "上海", "广州", "深圳", "成都"]
                elif next_field == "companions":
                    quick_actions = ["1个人", "2个人", "一家三口"]
                elif next_field == "days":
                    quick_actions = ["1天", "3天", "5天", "7天"]
                elif next_field == "budget":
                    quick_actions = ["3000", "5000", "8000"]
                else:
                    quick_actions = []

        elif phase == "recommending":
            selected_city = None
            for city in session["cities"]:
                if city["city"] in req.message:
                    selected_city = city["city"]
                    break

            if not selected_city:
                response_text = "没听清你想去哪儿，再说一次？或者直接点上面的卡片～"
                cities_data = session["cities"]
                quick_actions = [c["city"] for c in session["cities"][:3]]
            else:
                session["selected_city"] = selected_city
                session["phase"] = "generating_itinerary"
                session["asking_field"] = None

                response_text = f"好嘞，正在帮你规划 {selected_city} 的行程..."
                quick_actions = []

                pois_result = await asyncio.to_thread(
                    collect_pois_v2,
                    city=selected_city,
                    budget=int(user_info["budget"]),
                    companions=int(user_info["companions"]),
                    days=int(user_info["days"]),
                    intensity=user_info.get("intensity", "莫名其妙地玩"),
                    preferences=user_info.get("preferences", []),
                )

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
                session["itinerary"] = itinerary
                itinerary_data = itinerary

                response_text = f"✨ {selected_city} {user_info['days']}天行程出来了！\n\n"
                response_text += "你可以：\n• 看每日安排\n• 调整景点\n• 确认并导出"
                quick_actions = ["查看详细行程", "调整景点", "重新推荐城市"]

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
                quick_actions = ["调整景点", "确认行程", "重新推荐城市"]
            elif "调整" in req.message:
                response_text = "可以这样调整：\n• 告诉我去掉哪个点\n• 告诉我加什么类型的点\n• 或者我重新生成一版"
                quick_actions = ["重新生成行程", "换个城市", "确认当前行程"]
            elif "确认" in req.message or "导出" in req.message:
                # ⭐ 沉淀记忆
                try:
                    from ...memory.memory_agent import extract_and_save
                    uid = session.get("user_id", "demo")
                    trip = {
                        "city": session.get("selected_city"),
                        "days": user_info.get("days"),
                        "companions": user_info.get("companions"),
                        "preferences": user_info.get("preferences", []),
                        "itinerary": session.get("itinerary", []),
                    }
                    n = extract_and_save(uid, trip, feedback=req.message)
                    logger.info("沉淀记忆：%d 条", n)
                    response_text = "行程已确认！这次我记住了 ✨"
                except Exception as e:
                    logger.warning("沉淀记忆失败：%s", e)
                    response_text = "行程已确认！可以截图保存 ✨"

                quick_actions = ["重新开始", "换个城市"]
            else:
                response_text = "还想调整什么？或者我们重新开始～"
                quick_actions = ["查看详细行程", "重新推荐城市"]

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

    return ChatResponse(
        session_id=session_id,
        text=response_text,
        phase=session["phase"],
        cities=cities_data,
        itinerary=itinerary_data,
        quick_actions=quick_actions,
        user_info=session["user_info"],
        selected_city=session.get("selected_city"),
    )


# ─── 行程调整 Agent ──────────────────────────────────

@router.post("/adjust", response_model=AdjustResponse)
async def adjust_itinerary(req: AdjustRequest):
    """行程调整 Agent。LLM 解析意图 → 代码执行。"""
    from ...agents.itinerary_agent import parse_adjust_intent, execute_adjust

    try:
        poi_map = {p["id"]: p for p in req.pois}

        intent = await asyncio.to_thread(
            parse_adjust_intent, req.message, req.itinerary, poi_map,
        )

        new_itinerary, text = await asyncio.to_thread(
            execute_adjust, intent, req.itinerary, req.pois, req.city,
        )

        return AdjustResponse(itinerary=new_itinerary, text=text)
    except Exception as e:
        logger.exception("调整行程失败")
        raise HTTPException(500, f"调整失败：{e}")


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return session


# ─── SSE 流式对话（LangGraph 图驱动） ─────────────────

def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_chat(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """流式对话生成器 — LangGraph 图驱动。"""
    session = _get_session(session_id)

    if message and message.strip():
        session["messages"].append({"role": "user", "content": message})

    phase = session["phase"]
    yield _sse_event("session", {"session_id": session_id})

    try:
        from ...inspire_graph import (
            node_greeting, node_extract_info, node_ask_question,
            node_recommend_cities, node_select_and_collect,
            node_adjust_itinerary,
        )

        graph_state = {
            "session_id": session_id,
            "phase": phase,
            "message": message,
            "user_info": dict(session.get("user_info", {})),
            "asking_field": session.get("asking_field"),
            "cities": session.get("cities", []),
            "selected_city": session.get("selected_city"),
            "itinerary": session.get("itinerary"),
            "user_profile": dict(session.get("user_profile", {})),
            "memory_block": session.get("memory_block", ""),
            "user_id": session.get("user_id", "demo"),
            "tool_results": [],
            "extracted": {},
            "quick_actions": [],
            "response_text": "",
            "pois_result": {},
            "events": [],
            "error": None,
            "messages_history": session.get("messages", [])[-10:],  # P6: 最近 10 条对话历史
        }

        if phase == "greeting":
            graph_state = await node_greeting(graph_state)
            session["phase"] = "collecting_info"
            session["user_profile"] = graph_state.get("user_profile", {})
            session["memory_block"] = graph_state.get("memory_block", "")

        elif phase == "collecting_info":
            graph_state = await node_extract_info(graph_state)
            session["user_info"] = graph_state["user_info"]

            from .inspire import _check_info_complete
            complete, missing = _check_info_complete(graph_state["user_info"])

            if complete:
                session["phase"] = "recommending"
                session["asking_field"] = None
                graph_state = await node_recommend_cities(graph_state)
                session["cities"] = graph_state.get("cities", [])
            else:
                graph_state = await node_ask_question(graph_state)
                session["asking_field"] = graph_state["asking_field"]

        elif phase == "recommending":
            # 用户选择城市
            selected_city = None
            for city in session.get("cities", []):
                if city["city"] in message:
                    selected_city = city["city"]
                    break

            if not selected_city:
                response_text = "没听清你想去哪儿，再说一次？或者直接点上面的卡片～"
                for i in range(0, len(response_text), 3):
                    graph_state["events"].append({"event": "text_chunk", "data": {"content": response_text[i:i+3]}})
                graph_state["events"].append({"event": "quick_actions", "data": {"actions": [c["city"] for c in session.get("cities", [])[:3]]}})
            else:
                session["selected_city"] = selected_city
                session["phase"] = "generating_itinerary"
                graph_state["selected_city"] = selected_city
                graph_state = await node_select_and_collect(graph_state)
                session["itinerary"] = graph_state.get("itinerary")

        elif phase == "generating_itinerary":
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
                graph_state["events"].append({"event": "quick_actions", "data": {"actions": ["调整景点", "确认行程", "重新推荐城市"]}})
            elif "确认" in message or "导出" in message:
                try:
                    from ...memory.memory_agent import extract_and_save
                    uid = session.get("user_id", "demo")
                    trip = {
                        "city": session.get("selected_city"),
                        "days": session["user_info"].get("days"),
                        "companions": session["user_info"].get("companions"),
                        "preferences": session["user_info"].get("preferences", []),
                        "itinerary": session.get("itinerary", []),
                    }
                    extract_and_save(uid, trip, feedback=message)
                    response_text = "行程已确认！这次我记住了 ✨"
                except Exception:
                    response_text = "行程已确认！可以截图保存 ✨"
                for i in range(0, len(response_text), 3):
                    graph_state["events"].append({"event": "text_chunk", "data": {"content": response_text[i:i+3]}})
                graph_state["events"].append({"event": "quick_actions", "data": {"actions": ["重新开始", "换个城市"]}})
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
async def inspire_chat_stream(req: ChatRequest):
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