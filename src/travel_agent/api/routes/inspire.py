"""灵感漫游对话 API — 像聊天一样规划旅行。

统一入口 /api/inspire/chat，LLM + 正则降级提取用户意图。
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...llm import get_llm
from ...agents.destination import recommend_cities
from ...agents.poi_collector import collect_pois_v2

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── 会话存储（内存版，生产环境应接 Redis）──────────────
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
            "asking_field": None,      # ⭐ 当前正在追问的字段
        }
    return _sessions[session_id]


# ─── 请求/响应模型 ──────────────────────────────────────

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


# ─── 行程富化 ──────────────────────────────────────────

def _enrich_itinerary(
    initial: list[dict],
    pois: list[dict],
    hotels: list[dict],
) -> list[dict]:
    """把 collect_pois_v2 返回的 initial_itinerary 转成前端期望的格式。"""
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

        result.append({
            "day": day_schedule.get("day", 0),
            "items": day_items,
            "total_cost": total_cost,
        })

    return result


# ─── 正则降级提取（LLM 失败时的兜底方案）───────────────

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

# 字段中文名（用于 prompt）
_FIELD_LABELS = {
    "origin": "出发地城市名",
    "budget": "总预算数字（元）",
    "days": "出行天数数字",
    "companions": "出行人数数字",
}


def _regex_extract(
    message: str,
    existing: dict,
    asking_field: str | None = None,
) -> dict:
    """用正则从消息中提取结构化信息（LLM 失败时的降级方案）。

    ⭐ asking_field：上一轮追问的字段。用户回复纯数字/短句时，优先按它解读。
    """
    msg = message.strip()
    if not msg:
        return existing

    clean = msg.strip().rstrip("。！？!?,，")

    # ⭐ 上下文优先：正在追问某字段 + 用户回复纯数字
    if asking_field and re.fullmatch(r"\d{1,6}", clean):
        n = int(clean)
        if asking_field == "days" and 1 <= n <= 30:
            existing["days"] = n
            # 已经拿到答案，不再进入下面的通用解析
            # 但允许同时识别其他字段（比如"3天2人"），下面的逻辑依然跑
        elif asking_field == "companions" and 1 <= n <= 30:
            existing["companions"] = n
        elif asking_field == "budget" and 100 <= n <= 999999:
            existing["budget"] = n

    # ⭐ 正在追问 origin + 用户回复 2-4 字短词
    if asking_field == "origin" and 2 <= len(clean) <= 4 and "origin" not in existing:
        for city in _COMMON_CITIES:
            if city == clean or city in clean or clean in city:
                existing["origin"] = city
                break
        else:
            # 不在常见城市表里也直接存，允许小城市/国外城市
            existing["origin"] = clean

    # 1. 出发地
    if "origin" not in existing or not existing["origin"]:
        city_match = re.search(r"(?:去|从|到|出发|前往)\s*([\u4e00-\u9fa5]{2,4})", msg)
        if city_match:
            candidate = city_match.group(1)
            for city in _COMMON_CITIES:
                if city in candidate or candidate in city:
                    existing["origin"] = city
                    break
        if "origin" not in existing:
            city_match = re.search(r"([\u4e00-\u9fa5]{2,4})(?:玩|旅游|旅行|吗|吧|呀|！|!|$)", msg)
            if city_match:
                candidate = city_match.group(1)
                for city in _COMMON_CITIES:
                    if city == candidate or city in candidate or candidate in city:
                        existing["origin"] = city
                        break
        if "origin" not in existing:
            if 2 <= len(clean) <= 4:
                for city in _COMMON_CITIES:
                    if city == clean or clean in city or city in clean:
                        existing["origin"] = city
                        break

    # 2. 预算
    if "budget" not in existing or not existing["budget"]:
        range_match = re.search(r"(\d{2,5})\s*(?:到|-|~|至)\s*(\d{2,5})", msg)
        if range_match:
            existing["budget"] = int(range_match.group(2))
            existing["budget_range"] = [
                int(range_match.group(1)), int(range_match.group(2)),
            ]
        else:
            budget_match = re.search(
                r"(?:预算|准备|花|大概|约)?\s*(\d{3,6})\s*(?:元|块|钱|元预算)?", msg
            )
            if budget_match:
                existing["budget"] = int(budget_match.group(1))

    # 3. 天数
    if "days" not in existing or not existing["days"]:
        days_match = re.search(r"(?:玩|待|呆|旅游)?\s*(\d{1,2})\s*天", msg)
        if days_match:
            existing["days"] = int(days_match.group(1))

    # 4. 人数
    if "companions" not in existing or not existing["companions"]:
        comp_match = re.search(r"(\d{1,2})\s*(?:人|个)", msg)
        if comp_match:
            existing["companions"] = int(comp_match.group(1))
        elif re.search(r"独自|一个人|solo|单独", msg):
            existing["companions"] = 1
        elif re.search(r"情侣|两人|两个人|俩", msg):
            existing["companions"] = 2
        elif re.search(r"一家三口|三人|三个", msg):
            existing["companions"] = 3
        elif re.search(r"全家|一家人|一家", msg):
            existing["companions"] = 4

    # 5. 偏好
    if "preferences" not in existing:
        existing["preferences"] = []
    for keyword, tag in _PREF_MAP.items():
        if keyword in msg and tag not in existing["preferences"]:
            existing["preferences"].append(tag)

    # 6. 强度
    if "intensity" not in existing or not existing["intensity"]:
        for keyword, intensity in _INTENSITY_MAP.items():
            if keyword in msg:
                existing["intensity"] = intensity
                break

    return existing


# ─── LLM 辅助函数 ──────────────────────────────────────

async def _extract_user_info(
    message: str,
    existing: dict,
    asking_field: str | None = None,
) -> dict:
    """从用户消息中提取关键信息。

    ⭐ asking_field：上一轮追问的字段，作为 LLM 理解"纯数字回复"的上下文。
    """
    # 第一层：正则快速提取（带上下文）
    result = _regex_extract(message, dict(existing), asking_field)

    llm = get_llm(json_mode=True)

    # ⭐ 上下文提示
    context_hint = ""
    if asking_field:
        label = _FIELD_LABELS.get(asking_field, asking_field)
        context_hint = (
            f"\n【上下文】上一轮助手正在追问【{label}】。"
            f"如果用户回复是一个纯数字或简短回答（如 \"2\"），"
            f"优先理解为对【{asking_field}】的回复（如 days=2）。\n"
        )

    prompt = f"""你是旅行规划助手的信息提取器。从用户消息中提取所有关键信息，返回 JSON。
{context_hint}
【已有信息】{json.dumps(existing, ensure_ascii=False)}
【用户消息】{message}

【提取字段】
- origin: 出发地城市名（如 "北京"、"东莞"）
- budget: 总预算数字，单位元（如 5000）。区间"200到500"取上限 500
- days: 出行天数数字（如 3）
- companions: 人数数字（如 2）。"一个人"→1，"情侣"→2，"一家三口"→3
- preferences: 偏好标签列表，从 [美食/自然/历史/购物/摄影/冒险/休闲] 里选
- intensity: 旅游强度，只能是 "边走边躺" / "莫名其妙地玩" / "死了都要逛"
- no_hotel: 布尔，用户说不住宿/不过夜时为 true
- nearby: 布尔，用户说"附近""周边""近一点"时为 true

【提取规则】
1. 只返回 NEW 信息（已有信息里已存在的字段不要重复返回）
2. 如果消息中没有新信息，返回空对象 {{}}
3. ⭐ 关键：如果【上下文】说明在追问某字段，且用户回复是纯数字，直接映射到那个字段
4. 只返回 JSON 对象，不要任何其他文字

【示例】
上下文问"计划玩几天"，用户答"2" → {{"days": 2}}
上下文问"几个人"，用户答"3" → {{"companions": 3}}
上下文问"预算多少"，用户答"5000" → {{"budget": 5000}}
用户说 "我只想一个人在附近城市逛一天，不住宿"
→ {{"companions":1, "days":1, "nearby":true, "no_hotel":true}}
用户说 "东莞，3天，预算5000，想吃美食"
→ {{"origin":"东莞", "days":3, "budget":5000, "preferences":["美食"]}}
"""

    try:
        resp = await asyncio.to_thread(llm.invoke, prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        raw = re.sub(r"^```json\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        data = json.loads(raw)
        # LLM 结果覆盖正则结果
        for key, value in data.items():
            if value is not None and value != "" and value != []:
                result[key] = value
        logger.info(
            "LLM 提取：asking=%s msg=%r → %s",
            asking_field, message, data,
        )
    except Exception as e:
        logger.warning("LLM 提取失败，使用正则结果：%s | 错误：%s", message, e)

    return result


async def _generate_question(missing_fields: list[str], user_info: dict) -> str:
    """根据缺失字段生成自然的追问，一次只问一个。"""
    field_prompts = {
        "origin": "您从哪里出发呢？告诉我城市名就好～",
        "budget": "这次旅行大概准备了多少预算呀？",
        "days": "计划玩几天呢？",
        "companions": "几个人一起去呀？",
    }

    if not missing_fields:
        return "信息都齐了！让我为你想想推荐哪些城市..."

    next_field = missing_fields[0]
    question = field_prompts.get(next_field, f"还需要了解您的{next_field}")

    known_parts = []
    if user_info.get("origin"):
        known_parts.append(f"从{user_info['origin']}出发")
    if user_info.get("days"):
        known_parts.append(f"玩{user_info['days']}天")
    if user_info.get("budget"):
        known_parts.append(f"预算{user_info['budget']}元")
    if user_info.get("companions"):
        known_parts.append(f"{user_info['companions']}个人")
    if user_info.get("no_hotel"):
        known_parts.append("不住宿")
    if user_info.get("nearby"):
        known_parts.append("附近城市")
    if user_info.get("preferences"):
        pref_text = "、".join(user_info["preferences"])
        known_parts.append(f"喜欢{pref_text}")

    if known_parts:
        context = "好的，" + "、".join(known_parts) + "，"
    else:
        context = ""

    return f"{context}{question}"


def _check_info_complete(user_info: dict) -> tuple[bool, list[str]]:
    """检查必需信息是否完整。"""
    required = ["origin", "budget", "days", "companions"]
    missing = [f for f in required if f not in user_info or not user_info[f]]
    return len(missing) == 0, missing


# ─── 核心对话逻辑 ──────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def inspire_chat(req: ChatRequest):
    """灵感漫游对话入口。"""
    session_id = req.session_id or str(uuid.uuid4())[:8]
    session = _get_session(session_id)

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
            response_text = (
                "你好呀！我是你的旅行规划助手 🌟\n\n"
                "告诉我你的出发地、预算、天数，我来帮你推荐最适合的城市！"
            )
            session["phase"] = "collecting_info"
            quick_actions = ["北京出发", "我想去成都", "3天预算5000", "帮我推荐几个城市"]

        elif phase == "collecting_info":
            # ⭐ 传入 asking_field 让提取器利用上下文
            user_info = await _extract_user_info(req.message, user_info, asking_field)
            session["user_info"] = user_info

            complete, missing = _check_info_complete(user_info)

            if complete:
                session["phase"] = "recommending"
                session["asking_field"] = None

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

                response_text = f"根据你的需求，我为你推荐了 {len(cities)} 个城市：\n\n"
                response_text += "👇 点击下方卡片查看详情，或直接告诉我你想去哪个城市～"
                quick_actions = [c["city"] for c in cities[:3]]
            else:
                response_text = await _generate_question(missing, user_info)
                next_field = missing[0] if missing else None
                session["asking_field"] = next_field      # ⭐ 记录本轮问的字段

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
                response_text = "没听清你想去哪个城市呢，可以再说一次吗？或者直接点击上面的城市卡片～"
                cities_data = session["cities"]
                quick_actions = [c["city"] for c in session["cities"][:3]]
            else:
                session["selected_city"] = selected_city
                session["phase"] = "generating_itinerary"
                session["asking_field"] = None

                response_text = f"好的！正在为你规划 {selected_city} 的行程..."
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

                itinerary = _enrich_itinerary(
                    pois_result.get("initial_itinerary", []),
                    pois_result.get("pois", []),
                    pois_result.get("hotels", []),
                )
                session["itinerary"] = itinerary
                session["_raw_pois"] = pois_result.get("pois", [])
                session["_raw_hotels"] = pois_result.get("hotels", [])
                itinerary_data = itinerary

                response_text = f"✨ {selected_city} {user_info['days']}天行程已生成！\n\n"
                response_text += "你可以：\n• 查看每日安排\n• 调整景点顺序\n• 确认行程并导出"
                quick_actions = ["查看详细行程", "调整景点", "重新推荐城市"]

        elif phase == "generating_itinerary":
            if "详细" in req.message or "查看" in req.message:
                response_text = "好的，这是详细的行程安排：\n\n"
                if session["itinerary"]:
                    period_map = {
                        "morning": "早上", "noon": "中午",
                        "afternoon": "下午", "evening": "晚上",
                    }
                    for day in session["itinerary"]:
                        response_text += f"**第{day['day']}天**\n"
                        for item in day.get("items", []):
                            display_name = item.get("name") or item.get("poi_id", "未知")
                            period = item.get("period", "")
                            response_text += f"  {period_map.get(period, '')}: {display_name}\n"
                        response_text += "\n"
                quick_actions = ["调整景点", "确认行程", "重新推荐城市"]
            elif "调整" in req.message:
                response_text = (
                    "目前支持以下调整方式：\n"
                    "• 告诉我你想去掉哪个景点\n"
                    "• 告诉我你想增加什么类型的景点\n"
                    "• 或者我可以重新生成一版"
                )
                quick_actions = ["重新生成行程", "换个城市", "确认当前行程"]
            elif "确认" in req.message or "导出" in req.message:
                response_text = "行程已确认！你可以截图保存，或者稍后我们会推出导出功能 ✨"
                quick_actions = ["重新开始", "换个城市"]
            else:
                response_text = "还有什么需要调整的吗？或者我们可以重新开始规划～"
                quick_actions = ["查看详细行程", "重新推荐城市"]

        else:
            response_text = "让我们重新开始吧！你想去哪里玩呢？"
            session["phase"] = "greeting"
            session["user_info"] = {}
            session["asking_field"] = None

    except Exception as e:
        logger.exception("对话处理失败")
        response_text = f"抱歉，出了点小问题：{str(e)}\n请重试或刷新页面。"

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
    )


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取会话历史（用于恢复）。"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return session