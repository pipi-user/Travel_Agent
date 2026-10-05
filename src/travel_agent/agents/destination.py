"""城市推荐 v3 — 372 个城市 + 距离估算 + 预算硬过滤 + 排名映射。

流程：
  1. 遍历 data/cities.json 里全部城市
  2. Haversine 距离 → 估算城际费
  3. 预算硬过滤（交通费都付不起的直接淘汰）
  4. 打分：base_score + 偏好 + 预算 + 距离
  5. 取 Top 6，按排名映射展示分
"""
import logging
from pathlib import Path
from urllib.parse import quote

from ..llm import get_llm
from ..config import settings
from .city_meta import get_all_cities, get_meta, distance_km

logger = logging.getLogger(__name__)

CITY_IMG_DIR = Path("data/city_images")


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

def recommend_cities(
    origin: str,
    budget: int,
    companions: int,
    days: int,
    intensity: str,
    preferences: list[str],
    month: int = 0,
) -> list[dict]:
    """推荐 6 座城市。纯本地计算，毫秒级。"""
    all_cities = get_all_cities()
    companions = max(1, companions)
    days = max(1, days)

    candidates = []

    for city in all_cities:
        # 跳过出发地
        if city == origin or (origin and city in origin):
            continue

        meta = get_meta(city)

        # ── 1. 距离 ──────────────────────────────────
        d = distance_km(origin, city)
        if d < 0:
            continue

        # ── 2. 城际费估算 ────────────────────────────
        one_way = _estimate_intercity_fee(d)
        roundtrip = one_way * 2 * companions

        # ── 3. 预算过滤 ──────────────────────────────
        remaining = budget - roundtrip
        if remaining <= 0:
            continue

        daily_remaining = remaining / days
        city_daily_total = meta["daily_cost"] * companions
        hard = city_daily_total * 0.85

        if daily_remaining < hard:
            continue

        # ── 4. 打分 ─────────────────────────────────
        base = meta["base_score"]
        pref = _calc_preference_score(meta["tags"], preferences)

        # 预算分数：0.5 - 1.0
        budget_ratio = min(1.0, daily_remaining / max(city_daily_total, 1))
        budget_score = 0.5 + budget_ratio * 0.5

        # 距离分数：< 500km +0.5，> 2000km -1.0
        if d < 300:
            dist_bonus = 0.8
        elif d < 500:
            dist_bonus = 0.5
        elif d < 1000:
            dist_bonus = 0.0
        elif d < 1500:
            dist_bonus = -0.3
        elif d < 2000:
            dist_bonus = -0.6
        else:
            dist_bonus = -1.0

        raw = base + pref * 1.5 + budget_score * 0.5 + dist_bonus

        candidates.append({
            "city": city,
            "tags": meta["tags"],
            "daily_cost": meta["daily_cost"],
            "raw_score": raw,
            "distance_km": round(d, 1),
        })

    logger.info(
        "候选城市 %d 个（出发地 %s，预算 %d，%d 人 %d 天）",
        len(candidates), origin, budget, companions, days,
    )

    if not candidates:
        return []

    # ── 5. 排序 → Top 6 ─────────────────────────────
    candidates.sort(key=lambda x: -x["raw_score"])
    top6 = candidates[:6]

    # ── 6. 排名映射展示分（9.8 → 7.8） ──────────────
    result = []
    for rank, c in enumerate(top6):
        display_score = round(9.8 - rank * 0.4, 1)
        result.append({
            "city": c["city"],
            "score": display_score,
            "reason": _generate_reason(c["city"], c["tags"], preferences),
            "image_url": "",
            "intro": "",
            "tags": c["tags"][:3],
            "daily_cost": c["daily_cost"],
        })

    # ── 7. LLM 简介 + 图片 ──────────────────────────
    for c in result:
        c["intro"] = _llm_city_intro(c["city"])
        c["image_url"] = _city_image_url(c["city"])

    return result


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def _estimate_intercity_fee(distance_km: float) -> float:
    """按直线距离估算单程票价（元）。"""
    if distance_km < 300:
        return 40 + distance_km * 0.35
    elif distance_km < 800:
        return distance_km * 0.42
    elif distance_km < 1500:
        return distance_km * 0.48
    else:
        return distance_km * 0.55


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