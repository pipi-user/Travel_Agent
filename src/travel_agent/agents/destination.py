"""城市推荐 v2 — 适合度分数由后端代码计算，LLM 仅生成简短介绍。

适合度 = 偏好匹配度 × 0.4 + 预算合理度 × 0.3 + 季节适配 × 0.3
"""
import logging
import re

from ..llm import get_llm
from ..config import settings

logger = logging.getLogger(__name__)

# 城市 → 标签集合（用于偏好匹配）
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
}

# 城市 → 最佳旅游月份
CITY_BEST_MONTHS: dict[str, list[int]] = {
    "北京": [4, 5, 9, 10],
    "上海": [3, 4, 5, 9, 10, 11],
    "广州": [10, 11, 12, 1, 2, 3],
    "深圳": [10, 11, 12, 1, 2, 3],
    "成都": [3, 4, 5, 6, 9, 10, 11],
    "杭州": [3, 4, 5, 9, 10, 11],
    "西安": [3, 4, 5, 9, 10, 11],
    "重庆": [3, 4, 5, 9, 10, 11],
    "厦门": [3, 4, 5, 10, 11, 12],
    "大理": [3, 4, 5, 6, 9, 10, 11],
    "丽江": [3, 4, 5, 6, 9, 10, 11],
    "三亚": [10, 11, 12, 1, 2, 3],
    "桂林": [4, 5, 6, 9, 10, 11],
    "长沙": [3, 4, 5, 9, 10, 11],
    "武汉": [3, 4, 10, 11],
    "南京": [3, 4, 5, 9, 10, 11],
    "青岛": [5, 6, 7, 8, 9],
    "苏州": [3, 4, 5, 9, 10, 11],
    "昆明": [3, 4, 5, 6, 7, 8, 9, 10, 11],
    "哈尔滨": [1, 2, 6, 7, 8, 12],
}

# 城市 → 预估日均花费（元）
CITY_DAILY_COST: dict[str, int] = {
    "北京": 600, "上海": 700, "广州": 450, "深圳": 600,
    "成都": 400, "杭州": 550, "西安": 400, "重庆": 400,
    "厦门": 500, "大理": 350, "丽江": 400, "三亚": 600,
    "桂林": 350, "长沙": 350, "武汉": 350, "南京": 450,
    "青岛": 450, "苏州": 500, "昆明": 350, "哈尔滨": 400,
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
    """推荐 6 座城市，适合度由代码计算。"""
    daily_budget = budget / max(days, 1)

    scored_cities = []
    for city, tags in CITY_TAGS.items():
        # 跳过出发地
        if city in origin:
            continue

        # 1. 偏好匹配度 (0-1)
        pref_score = _calc_preference_score(tags, preferences)

        # 2. 预算合理度 (0-1)
        budget_score = _calc_budget_score(city, daily_budget)

        # 3. 季节适配 (0-1)
        season_score = _calc_season_score(city, month) if month > 0 else 0.5

        # 综合分数
        total = pref_score * 0.4 + budget_score * 0.3 + season_score * 0.3
        total = round(min(max(total, 0), 1) * 10, 1)  # 转为 0-10 分

        scored_cities.append({
            "city": city,
            "score": total,
            "reason": _generate_reason(city, tags, preferences),
            "image_url": "",  # 前端通过 city-image-map.json 匹配
            "intro": "",      # 稍后由 LLM 填充
            "_tags": tags,
        })

    # 按分数降序排列，取前 6
    scored_cities.sort(key=lambda x: -x["score"])
    top6 = scored_cities[:6]

    # LLM 生成城市简介（并发，失败不影响）
    for c in top6:
        c["intro"] = _llm_city_intro(c["city"])

    # 清理内部字段
    for c in top6:
        c.pop("_tags", None)

    return top6


def _calc_preference_score(city_tags: list[str], preferences: list[str]) -> float:
    """计算偏好匹配度。"""
    if not preferences:
        return 0.5  # 无偏好时给中等分

    from .preference_scorer import PREFERENCE_TAG_MAP
    matches = 0
    for pref in preferences:
        mapped = PREFERENCE_TAG_MAP.get(pref, [])
        if any(t in city_tags for t in mapped):
            matches += 1

    return min(matches / max(len(preferences), 1), 1.0)


def _calc_budget_score(city: str, daily_budget: float) -> float:
    """计算预算合理度。"""
    city_cost = CITY_DAILY_COST.get(city, 500)
    if daily_budget >= city_cost * 1.2:
        return 1.0
    elif daily_budget >= city_cost:
        return 0.8
    elif daily_budget >= city_cost * 0.8:
        return 0.5
    elif daily_budget >= city_cost * 0.5:
        return 0.3
    else:
        return 0.1


def _calc_season_score(city: str, month: int) -> float:
    """计算季节适配度。"""
    best = CITY_BEST_MONTHS.get(city, [])
    if not best:
        return 0.5
    if month in best:
        return 1.0
    # 相邻月份给部分分
    if (month - 1) in best or (month + 1) in best:
        return 0.7
    return 0.3


def _generate_reason(city: str, tags: list[str], preferences: list[str]) -> str:
    """生成一句话推荐语。"""
    # 优先用匹配到的标签
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

    # 默认用城市特色标签
    highlights = tags[:2] if tags else ["特色"]
    return f"{city}，{'与'.join(highlights)}的邂逅"


def _llm_city_intro(city: str) -> str:
    """LLM 生成城市简短介绍（1 句话，20 字内）。失败返回默认。"""
    try:
        llm = get_llm()
        resp = llm.invoke(f"用不超过 20 个字介绍{city}的旅游特色，只输出介绍文字：")
        text = (resp.content if hasattr(resp, "content") else str(resp)).strip()
        # 清理引号
        text = text.strip("\"'「」『』")
        if len(text) > 30:
            text = text[:30]
        return text
    except Exception as e:
        logger.debug("LLM 城市介绍失败：%s", e)
        return f"{city}，值得一去"
