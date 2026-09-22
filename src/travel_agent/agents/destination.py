"""城市推荐 v2 — 适合度分数由后端代码计算，LLM 仅生成简短介绍。"""
import logging
from pathlib import Path
from urllib.parse import quote

from ..llm import get_llm
from ..config import settings

logger = logging.getLogger(__name__)

CITY_IMG_DIR = Path("data/city_images")

# 城市 → 标签
CITY_TAGS: dict[str, list[str]] = {
    "北京": ["历史", "文化", "古迹", "博物馆", "皇家", "胡同"],
    "上海": ["现代", "购物", "美食", "都市", "夜景", "艺术"],
    "广州": ["美食", "本地菜", "小吃", "岭南", "花市", "休闲"],
    "深圳": ["现代", "购物", "科技", "主题公园", "海滨"],
    "成都": ["美食", "休闲", "熊猫", "茶馆", "慢生活", "火锅"],
    "杭州": ["自然", "山水", "湖", "茶园", "历史", "丝绸"],
    "西安": ["历史", "古迹", "美食", "文化", "兵马俑", "回民街"],
    "重庆": ["美食", "火锅", "夜景", "山城", "历史", "网红"],
    "厦门": ["海滨", "文艺", "休闲", "摄影", "鼓浪屿", "海鲜"],
    "大理": ["自然", "休闲", "摄影", "古城", "洱海", "民族"],
    "丽江": ["古城", "自然", "摄影", "雪山", "民族", "休闲"],
    "三亚": ["海滨", "度假", "海鲜", "休闲", "热带", "沙滩"],
    "桂林": ["自然", "山水", "摄影", "梯田", "漓江", "户外"],
    "长沙": ["美食", "小吃", "网红", "历史", "娱乐", "夜生活"],
    "武汉": ["美食", "历史", "樱花", "湖", "文化", "热干面"],
    "南京": ["历史", "文化", "美食", "古迹", "民国", "梧桐"],
    "青岛": ["海滨", "啤酒", "海鲜", "欧式", "休闲", "摄影"],
    "苏州": ["园林", "历史", "水乡", "丝绸", "精致", "古镇"],
    "昆明": ["自然", "花海", "春城", "民族", "休闲", "石林"],
    "哈尔滨": ["冰雪", "俄式", "美食", "冬季", "建筑", "冰雕"],
    "郑州": ["历史", "中原", "少林", "美食", "文化", "交通枢纽"],
    "天津": ["欧式", "海河", "相声", "美食", "近代", "休闲"],
    "济南": ["泉水", "历史", "大明湖", "齐鲁", "文化", "休闲"],
    "珠海": ["海滨", "休闲", "浪漫", "澳门", "度假", "情侣路"],
    "宁波": ["港口", "历史", "海鲜", "天一阁", "江南", "商帮"],
    "福州": ["榕城", "温泉", "三坊七巷", "闽菜", "历史", "休闲"],
    "合肥": ["科教", "包公", "徽菜", "三国", "环湖", "休闲"],
    "佛山": ["武术", "岭南", "祖庙", "美食", "陶瓷", "文化"],
    "无锡": ["太湖", "园林", "鼋头渚", "灵山", "江南", "影视"],
    "贵阳": ["山水", "避暑", "酸汤", "民俗", "甲秀楼", "休闲"],
}

# ⭐ 城市旅游热度基础分（0-10，人工粗估）
CITY_BASE_SCORE: dict[str, float] = {
    "北京": 9.3, "上海": 9.1, "广州": 8.6, "深圳": 8.3,
    "成都": 9.2, "杭州": 9.0, "西安": 8.9, "重庆": 8.8,
    "厦门": 8.6, "大理": 8.5, "丽江": 8.6, "三亚": 8.7,
    "桂林": 8.4, "长沙": 8.6, "武汉": 8.2, "南京": 8.6,
    "青岛": 8.5, "苏州": 8.6, "昆明": 8.3, "哈尔滨": 8.2,
    "郑州": 7.8, "天津": 8.0, "济南": 7.8, "珠海": 8.0,
    "宁波": 7.8, "福州": 7.9, "合肥": 7.6, "佛山": 7.8,
    "无锡": 7.9, "贵阳": 7.8,
}

CITY_BEST_MONTHS: dict[str, list[int]] = {
    "北京": [4, 5, 9, 10], "上海": [3, 4, 5, 9, 10, 11],
    "广州": [10, 11, 12, 1, 2, 3], "深圳": [10, 11, 12, 1, 2, 3],
    "成都": [3, 4, 5, 6, 9, 10, 11], "杭州": [3, 4, 5, 9, 10, 11],
    "西安": [3, 4, 5, 9, 10, 11], "重庆": [3, 4, 5, 9, 10, 11],
    "厦门": [3, 4, 5, 10, 11, 12], "大理": [3, 4, 5, 6, 9, 10, 11],
    "丽江": [3, 4, 5, 6, 9, 10, 11], "三亚": [10, 11, 12, 1, 2, 3],
    "桂林": [4, 5, 6, 9, 10, 11], "长沙": [3, 4, 5, 9, 10, 11],
    "武汉": [3, 4, 10, 11], "南京": [3, 4, 5, 9, 10, 11],
    "青岛": [5, 6, 7, 8, 9], "苏州": [3, 4, 5, 9, 10, 11],
    "昆明": [3, 4, 5, 6, 7, 8, 9, 10, 11], "哈尔滨": [1, 2, 6, 7, 8, 12],
    "郑州": [3, 4, 5, 9, 10, 11], "天津": [4, 5, 9, 10],
    "济南": [4, 5, 9, 10], "珠海": [3, 4, 5, 10, 11, 12],
    "宁波": [3, 4, 5, 9, 10, 11], "福州": [3, 4, 5, 9, 10, 11],
    "合肥": [3, 4, 5, 9, 10, 11], "佛山": [3, 4, 10, 11],
    "无锡": [3, 4, 5, 9, 10, 11], "贵阳": [4, 5, 6, 7, 8, 9, 10],
}

CITY_DAILY_COST: dict[str, int] = {
    "北京": 600, "上海": 700, "广州": 450, "深圳": 600,
    "成都": 400, "杭州": 550, "西安": 400, "重庆": 400,
    "厦门": 500, "大理": 350, "丽江": 400, "三亚": 600,
    "桂林": 350, "长沙": 350, "武汉": 350, "南京": 450,
    "青岛": 450, "苏州": 500, "昆明": 350, "哈尔滨": 400,
    "郑州": 350, "天津": 450, "济南": 400, "珠海": 500,
    "宁波": 500, "福州": 450, "合肥": 380, "佛山": 400,
    "无锡": 450, "贵阳": 350,
}


def recommend_cities(
    origin: str,
    budget: int,
    companions: int,
    days: int,
    intensity: str,
    preferences: list[str],
    month: int = 0,
) -> list[dict]:
    """推荐 6 座城市。

    两步：
      1. 原始分（base + 偏好/预算/季节加成）→ 用于排序
      2. 展示分（按排名映射到 [7.8, 9.8]）→ 保证永远有差异
    """
    daily_budget = budget / max(days, 1)

    # ── 1. 算原始分 ─────────────────────────────────
    raw_scores = []
    for city, tags in CITY_TAGS.items():
        if city in origin:
            continue

        base = CITY_BASE_SCORE.get(city, 7.5)
        pref = _calc_preference_score(tags, preferences)
        budg = _calc_budget_score(city, daily_budget)
        seas = _calc_season_score(city, month) if month > 0 else 0.5

        raw = base + pref * 1.5 + budg * 0.5 + seas * 0.5
        raw_scores.append((city, tags, raw))

    # ── 2. 按原始分降序 ─────────────────────────────
    raw_scores.sort(key=lambda x: -x[2])
    top6 = raw_scores[:6]

    # ── 3. 排名映射展示分：第1名 9.8，每降一名减 0.4 ──
    scored_cities = []
    for rank, (city, tags, _) in enumerate(top6):
        display_score = round(9.8 - rank * 0.4, 1)

        scored_cities.append({
            "city": city,
            "score": display_score,
            "reason": _generate_reason(city, tags, preferences),
            "image_url": "",
            "intro": "",
            "tags": tags[:3],
            "daily_cost": CITY_DAILY_COST.get(city, 500),
        })

    # ── 4. 填充简介 + 图片 ──────────────────────────
    for c in scored_cities:
        c["intro"] = _llm_city_intro(c["city"])
        c["image_url"] = _city_image_url(c["city"])

    return scored_cities


def _calc_preference_score(city_tags: list[str], preferences: list[str]) -> float:
    if not preferences:
        return 0.5
    from .preference_scorer import PREFERENCE_TAG_MAP
    matches = 0
    for pref in preferences:
        mapped = PREFERENCE_TAG_MAP.get(pref, [])
        if any(t in city_tags for t in mapped):
            matches += 1
    return min(matches / max(len(preferences), 1), 1.0)


def _calc_budget_score(city: str, daily_budget: float) -> float:
    """预算合理度。日预算远高于城市日均时，分数略降（避免全满分）。"""
    city_cost = CITY_DAILY_COST.get(city, 500)
    ratio = daily_budget / max(city_cost, 1)

    if ratio >= 3.0:
        return 0.7
    if ratio >= 1.5:
        return 0.9
    if ratio >= 1.0:
        return 1.0
    if ratio >= 0.7:
        return 0.5
    return max(0.1, ratio * 0.5)


def _calc_season_score(city: str, month: int) -> float:
    best = CITY_BEST_MONTHS.get(city, [])
    if not best:
        return 0.5
    if month in best:
        return 1.0
    if (month - 1) in best or (month + 1) in best:
        return 0.7
    return 0.3


def _generate_reason(city: str, tags: list[str], preferences: list[str]) -> str:
    if preferences:
        from .preference_scorer import PREFERENCE_TAG_MAP
        matched = []
        for pref in preferences:
            mapped = PREFERENCE_TAG_MAP.get(pref, [])
            for t in mapped:
                if t in tags:
                    matched.append(t)
        if matched:
            return f"{city}，{'、'.join(matched[:2])}之旅"
    highlights = tags[:2] if tags else ["特色"]
    return f"{city}，{'与'.join(highlights)}的邂逅"


def _llm_city_intro(city: str) -> str:
    try:
        llm = get_llm()
        resp = llm.invoke(f"用不超过 20 个字介绍{city}的旅游特色，只输出介绍文字：")
        text = (resp.content if hasattr(resp, "content") else str(resp)).strip()
        text = text.strip("\"'「」『』")
        return text[:30] if len(text) > 30 else text
    except Exception as e:
        logger.debug("LLM 城市介绍失败：%s", e)
        return f"{city}，值得一去"


def _city_image_url(city: str) -> str:
    for ext in ("jpg", "jpeg", "png", "webp"):
        if (CITY_IMG_DIR / f"{city}.{ext}").exists():
            return f"http://localhost:8000/static/city/{quote(city)}.{ext}"

    from ..cache import get as cache_get, set as cache_set, make_key
    key = make_key("city_img_v1", city)
    hit = cache_get(key, 86400 * 7)
    if hit is not None:
        return hit
    if not settings.tavily_api_key:
        return ""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        r = client.search(
            query=f"{city} 城市 风景 地标",
            include_images=True, max_results=3, search_depth="basic",
        )
        imgs = r.get("images") or []
        result = imgs[0] if imgs else ""
        cache_set(key, result)
        return result
    except Exception as e:
        logger.debug("城市图搜索失败 %s: %s", city, e)
        cache_set(key, "")
        return ""