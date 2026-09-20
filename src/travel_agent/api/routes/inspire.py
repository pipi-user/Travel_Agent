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


class ItineraryDay(BaseModel):
    day: int
    items: list[dict]
    total_cost: float


class ChatResponse(BaseModel):
    session_id: str
    text: str
    phase: str
    cities: Optional[list[CityCard]] = None
    itinerary: Optional[list[ItineraryDay]] = None
    quick_actions: list[str] = []


# ─── 正则降级提取（LLM 失败时的兜底方案）───────────────

# 常见城市名（用于正则匹配）
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


def _regex_extract(message: str, existing: dict) -> dict:
    """用正则从消息中提取结构化信息（LLM 失败时的降级方案）。"""
    msg = message.strip()
    if not msg:
        return existing

    # 1. 出发地：匹配 "去/从/到 + 城市名" 或单独的城市名（2-4字）
    if "origin" not in existing or not existing["origin"]:
        # 先尝试带上下文的匹配
        city_match = re.search(r'(?:去|从|到|出发|前往)\s*([\u4e00-\u9fa5]{2,4})', msg)
        if city_match:
            candidate = city_match.group(1)
            for city in _COMMON_CITIES:
                if city in candidate or candidate in city:
                    existing["origin"] = city
                    break
        if "origin" not in existing:
            # 再尝试 "城市名 + 玩/旅游" 后缀
            city_match = re.search(r'([\u4e00-\u9fa5]{2,4})(?:玩|旅游|旅行|吗|吧|呀|！|!|$)', msg)
            if city_match:
                candidate = city_match.group(1)
                for city in _COMMON_CITIES:
                    if city == candidate or city in candidate or candidate in city:
                        existing["origin"] = city
                        break
        if "origin" not in existing:
            # 最后尝试：消息本身就是 2-4 字城市名
            clean = msg.strip().rstrip('。！？!?,，')
            if 2 <= len(clean) <= 4:
                for city in _COMMON_CITIES:
                    if city == clean or clean in city or city in clean:
                        existing["origin"] = city
                        break

    # 2. 预算：匹配 "预算/准备/花 + 数字" 或 "数字到数字" 区间
    if "budget" not in existing or not existing["budget"]:
        # 先尝试区间匹配 "200到500" / "200-500"
        range_match = re.search(r'(\d{2,5})\s*(?:到|-|~|至)\s*(\d{2,5})', msg)
        if range_match:
            # 取区间上限作为预算
            existing["budget"] = int(range_match.group(2))
            existing["budget_range"] = [int(range_match.group(1)), int(range_match.group(2))]
        else:
            budget_match = re.search(r'(?:预算|准备|花|大概|约)?\s*(\d{3,6})\s*(?:元|块|钱|元预算)?', msg)
            if budget_match:
                existing["budget"] = int(budget_match.group(1))

    # 3. 天数：匹配 "数字 + 天" 或 "玩 + 数字 + 天"
    if "days" not in existing or not existing["days"]:
        days_match = re.search(r'(?:玩|待|呆|旅游)?\s*(\d{1,2})\s*天', msg)
        if days_match:
            existing["days"] = int(days_match.group(1))

    # 4. 人数：匹配 "数字 + 人/个" 或 "和 + 某人"
    if "companions" not in existing or not existing["companions"]:
        comp_match = re.search(r'(\d{1,2})\s*(?:人|个)', msg)
        if comp_match:
            existing["companions"] = int(comp_match.group(1))
        elif re.search(r'独自|一个人|solo|单独', msg):
            existing["companions"] = 1
        elif re.search(r'情侣|两人|两个人|俩', msg):
            existing["companions"] = 2
        elif re.search(r'一家三口|三人|三个', msg):
            existing["companions"] = 3
        elif re.search(r'全家|一家人|一家', msg):
            existing["companions"] = 4

    # 5. 偏好：关键词匹配
    if "preferences" not in existing:
        existing["preferences"] = []
    for keyword, tag in _PREF_MAP.items():
        if keyword in msg and tag not in existing["preferences"]:
            existing["preferences"].append(tag)

    # 6. 强度：关键词匹配
    if "intensity" not in existing or not existing["intensity"]:
        for keyword, intensity in _INTENSITY_MAP.items():
            if keyword in msg:
                existing["intensity"] = intensity
                break

    return existing


# ─── LLM 辅助函数 ──────────────────────────────────────

async def _extract_user_info(message: str, existing: dict) -> dict:
    """用 LLM 从用户消息中提取所有关键信息。
    
    策略：
    1. 先用正则快速提取（兜底）
    2. 再用 LLM 深度理解，提取隐含信息（如"一个人"→companions=1，"不住宿"→no_hotel=True）
    3. 合并结果，只保留新提取的字段
    """
    # 第一层：正则快速提取（始终执行，作为基线）
    result = _regex_extract(message, dict(existing))
    
    # 第二层：LLM 深度理解（提取隐含信息和复杂表达）
    llm = get_llm(json_mode=True)
    
    prompt = f"""你是旅行规划助手的信息提取器。从用户消息中提取所有关键信息，返回 JSON。

【已有信息】{json.dumps(existing, ensure_ascii=False)}
【用户消息】{message}

【提取字段】
- origin: 出发地城市名（如 "北京"、"东莞"）
- budget: 总预算数字，单位元（如 5000）。如果是区间"200到500"，取上限 500
- days: 出行天数数字（如 3）
- companions: 人数数字（如 2）。"一个人"→1，"情侣"→2，"一家三口"→3
- preferences: 偏好标签列表，可选值：美食/自然/历史/购物/摄影/冒险/休闲
- intensity: 旅游强度，只能是 "边走边躺" / "莫名其妙地玩" / "死了都要逛"
- no_hotel: 布尔值，用户明确说不住宿/不过夜时为 true
- nearby: 布尔值，用户说"附近""周边""近一点"时为 true

【提取规则】
1. 只返回 NEW 信息（已有信息中已存在的字段不要重复返回）
2. 如果消息中没有新信息，返回空对象 {{}}
3. 理解隐含信息："一个人"→companions=1，"想吃火锅"→preferences=["美食"]，"不住宿"→no_hotel=true
4. 只返回 JSON 对象，不要任何其他文字

【示例】
用户说 "我只想一个人在附近一个城市逛一天，不住宿" 
→ {{"companions":1, "days":1, "nearby":true, "no_hotel":true}}

用户说 "东莞，3天，预算5000，想吃美食"
→ {{"origin":"东莞", "days":3, "budget":5000, "preferences":["美食"]}}

用户说 "预算大概200到500吧"
→ {{"budget":500, "budget_range":[200,500]}}
"""
    
    try:
        resp = await asyncio.to_thread(llm.invoke, prompt)
        raw = resp.content if hasattr(resp, 'content') else str(resp)
        # 清理可能的 markdown 代码块包裹
        raw = re.sub(r'^```json\s*', '', raw.strip())
        raw = re.sub(r'\s*```$', '', raw.strip())
        data = json.loads(raw)
        # 合并 LLM 提取结果（LLM 结果优先，覆盖正则）
        for key, value in data.items():
            if value is not None and value != "" and value != []:
                result[key] = value
        logger.info("LLM 提取成功：%s → %s", message, data)
    except Exception as e:
        logger.warning("LLM 提取失败，使用正则结果：%s | 错误：%s", message, e)
        # 正则结果已在 result 中，直接使用
    
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
    
    # 只问第一个缺失字段
    next_field = missing_fields[0]
    question = field_prompts.get(next_field, f"还需要了解您的{next_field}")
    
    # 添加已收集信息的上下文，让用户感到被理解
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
        known_parts.append(f"想吃{pref_text}")
    
    if known_parts:
        context = "好的，" + "、".join(known_parts) + "，"
    else:
        context = ""
    
    return f"{context}{question}"


def _check_info_complete(user_info: dict) -> tuple[bool, list[str]]:
    """检查必需信息是否完整，返回 (是否完整，缺失字段列表)。
    
    必需字段：origin, budget, days, companions
    可选字段：preferences, intensity, no_hotel, nearby（不影响流程推进）
    """
    required = ["origin", "budget", "days", "companions"]
    missing = [f for f in required if f not in user_info or not user_info[f]]
    return len(missing) == 0, missing


# ─── 核心对话逻辑 ──────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def inspire_chat(req: ChatRequest):
    """灵感漫游对话入口。"""
    session_id = req.session_id or str(uuid.uuid4())[:8]
    session = _get_session(session_id)
    
    # 记录用户消息
    session["messages"].append({"role": "user", "content": req.message})
    
    phase = session["phase"]
    user_info = session["user_info"]
    
    response_text = ""
    cities_data = None
    itinerary_data = None
    quick_actions = []
    
    try:
        if phase == "greeting":
            # 首次问候
            response_text = "你好呀！我是你的旅行规划助手 🌟\n\n告诉我你的出发地、预算、天数，我来帮你推荐最适合的城市！"
            session["phase"] = "collecting_info"
            quick_actions = ["北京出发", "我想去成都", "3天预算5000", "帮我推荐几个城市"]
        
        elif phase == "collecting_info":
            # 提取信息
            user_info = await _extract_user_info(req.message, user_info)
            session["user_info"] = user_info
            
            complete, missing = _check_info_complete(user_info)
            
            if complete:
                # 信息收集完毕，生成城市推荐
                session["phase"] = "recommending"
                
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
                # 继续追问，提供快捷按钮
                response_text = await _generate_question(missing, user_info)
                # 只有当前要问的字段才显示快捷按钮
                next_field = missing[0] if missing else None
                if next_field == "origin":
                    quick_actions = ["北京", "上海", "广州", "深圳", "成都"]
                elif next_field == "companions":
                    quick_actions = ["1个人", "2个人", "一家三口"]
                else:
                    # 预算和天数让用户自由输入，不显示快捷按钮
                    quick_actions = []
        
        elif phase == "recommending":
            # 用户选择城市
            selected_city = None
            msg_lower = req.message.lower()
            
            for city in session["cities"]:
                if city["city"] in req.message:
                    selected_city = city["city"]
                    break
            
            if not selected_city:
                response_text = "没听清你想去哪个城市呢，可以再说一次吗？或者直接点击上面的城市卡片～"
                cities_data = session["cities"]
                quick_actions = [c["city"] for c in session["cities"][:3]]
            else:
                # 开始生成行程
                session["selected_city"] = selected_city
                session["phase"] = "generating_itinerary"
                
                response_text = f"好的！正在为你规划 {selected_city} 的行程..."
                quick_actions = []
                
                # 异步获取 POI 和生成行程
                pois_result = await asyncio.to_thread(
                    collect_pois_v2,
                    city=selected_city,
                    budget=int(user_info["budget"]),
                    companions=int(user_info["companions"]),
                    days=int(user_info["days"]),
                    intensity=user_info.get("intensity", "莫名其妙地玩"),
                    preferences=user_info.get("preferences", []),
                )
                
                itinerary = pois_result.get("initial_itinerary", [])
                session["itinerary"] = itinerary
                itinerary_data = itinerary
                
                response_text = f"✨ {selected_city} {user_info['days']}天行程已生成！\n\n"
                response_text += "你可以：\n• 查看每日安排\n• 调整景点顺序\n• 确认行程并导出"
                quick_actions = ["查看详细行程", "调整景点", "重新推荐城市"]
        
        elif phase == "generating_itinerary":
            # 行程展示后的交互
            if "详细" in req.message or "查看" in req.message:
                response_text = "好的，这是详细的行程安排：\n\n"
                if session["itinerary"]:
                    for day in session["itinerary"]:
                        response_text += f"**第{day['day']}天**\n"
                        for item in day.get("items", []):
                            poi_name = item.get("poi_id", "未知景点")
                            period = item.get("period", "")
                            period_map = {"morning": "早上", "noon": "中午", "afternoon": "下午", "evening": "晚上"}
                            response_text += f"  {period_map.get(period, '')}: {poi_name}\n"
                        response_text += "\n"
                quick_actions = ["调整景点", "确认行程", "重新推荐城市"]
            elif "调整" in req.message:
                response_text = "目前支持以下调整方式：\n• 告诉我你想去掉哪个景点\n• 告诉我你想增加什么类型的景点\n• 或者我可以重新生成一版"
                quick_actions = ["重新生成行程", "换个城市", "确认当前行程"]
            elif "确认" in req.message or "导出" in req.message:
                response_text = "行程已确认！你可以截图保存，或者稍后我们会推出导出功能 "
                quick_actions = ["重新开始", "换个城市"]
            else:
                response_text = "还有什么需要调整的吗？或者我们可以重新开始规划～"
                quick_actions = ["查看详细行程", "重新推荐城市"]
        
        else:
            response_text = "让我们重新开始吧！你想去哪里玩呢？"
            session["phase"] = "greeting"
            session["user_info"] = {}
    
    except Exception as e:
        logger.exception("对话处理失败")
        response_text = f"抱歉，出了点小问题：{str(e)}\n请重试或刷新页面。"
    
    # 记录 AI 回复
    session["messages"].append({"role": "assistant", "content": response_text})
    
    # 限制消息历史长度
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
