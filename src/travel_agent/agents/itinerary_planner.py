"""行程编排 v6 — 评分优先 + 特色加权 + 固定结构。

每天固定 7 个：
  早：1 餐 + 1 景点
  中：1 餐
  下午：2 景点
  晚：1 餐 + 1 景点

排序原则：
  1. 先按"评分 + 特色标签"降序排列
  2. 分池（早餐/正餐/夜宵），池内再排
  3. 景点也按评分排序，去同质，再地理聚集
"""
import logging
import math

logger = logging.getLogger(__name__)


# 只认最明确的早餐/夜宵关键词
BREAKFAST_KW = ["早茶", "早餐", "豆浆", "油条", "包子", "粥", "肠粉", "粿汁", "粿条"]
NIGHT_KW = ["夜宵", "宵夜", "烧烤", "大排档", "串吧", "酒吧"]

# 特色标签（出现即加权）
FEATURE_TAGS = ["本地菜", "特色", "老字号", "非遗", "招牌", "传统", "网红", "必吃"]

# 名字里的特色词
FEATURE_NAME_KW = ["潮汕", "汕头", "潮州", "特色", "老牌", "老字号", "正宗"]

CATEGORY_TAGS = [
    "博物馆", "公园", "寺庙", "古镇", "纪念馆", "艺术馆",
    "广场", "遗址", "园林", "城墙", "教堂", "步行街",
]


def _classify_food(name: str) -> str:
    if any(kw in name for kw in BREAKFAST_KW):
        return "breakfast"
    if any(kw in name for kw in NIGHT_KW):
        return "night"
    return "main"


def _rank_score(poi: dict) -> float:
    """综合排序分 = 评分 + 特色加权。"""
    base = float(poi.get("score", 0) or 0)
    tags = poi.get("tags", []) or []
    name = poi.get("name", "")

    bonus = 0.0
    if any(t in tags for t in FEATURE_TAGS):
        bonus += 2.0
    if any(kw in name for kw in FEATURE_NAME_KW):
        bonus += 1.0

    return base + bonus


def _haversine(p1: dict, p2: dict) -> float:
    lat1, lng1 = p1.get("lat", 0), p1.get("lng", 0)
    lat2, lng2 = p2.get("lat", 0), p2.get("lng", 0)
    if not all([lat1, lng1, lat2, lng2]):
        return 9999.0
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _primary_tag(poi: dict) -> str:
    tags = poi.get("tags", [])
    for t in tags:
        if t in CATEGORY_TAGS:
            return t
    return tags[0] if tags else "其他"


def _nearest_neighbor_sort(pois: list[dict]) -> list[dict]:
    """贪心最近邻排序。"""
    if not pois:
        return []
    remaining = list(pois)
    current = remaining.pop(0)
    result = [current]
    while remaining:
        nearest = min(remaining, key=lambda p: _haversine(current, p))
        result.append(nearest)
        remaining.remove(nearest)
        current = nearest
    return result


def _dedup_by_tag(pois: list[dict], max_per_tag: int) -> list[dict]:
    """同主标签最多保留 N 个。"""
    seen: dict[str, int] = {}
    result = []
    for p in pois:
        tag = _primary_tag(p)
        if seen.get(tag, 0) >= max_per_tag:
            continue
        result.append(p)
        seen[tag] = seen.get(tag, 0) + 1
    return result


def generate_initial_itinerary(
    attractions: list[dict],
    foods: list[dict],
    days: int,
    intensity: str,
) -> list[dict]:
    """生成行程。每天固定 7 个：3 食 + 4 景。"""
    days = max(days, 1)

    if not attractions and not foods:
        return [{"day": d, "items": []} for d in range(1, days + 1)]

    # ⭐ 1. 分池
    breakfast_pool = [f for f in foods if _classify_food(f.get("name", "")) == "breakfast"]
    night_pool = [f for f in foods if _classify_food(f.get("name", "")) == "night"]
    main_pool = [f for f in foods if _classify_food(f.get("name", "")) == "main"]

    # ⭐ 2. 池内按评分 + 特色加权降序
    breakfast_pool.sort(key=_rank_score, reverse=True)
    night_pool.sort(key=_rank_score, reverse=True)
    main_pool.sort(key=_rank_score, reverse=True)

    logger.info(
        "食物池：早 %d / 正 %d / 夜 %d",
        len(breakfast_pool), len(main_pool), len(night_pool),
    )
    logger.info("正餐排序前 5：%s", [f["name"] for f in main_pool[:5]])

    # ⭐ 3. 景点按评分降序 → 去同质 → 地理聚集
    attractions = sorted(attractions, key=_rank_score, reverse=True)
    attractions = _dedup_by_tag(attractions, max_per_tag=max(2, days))
    attrs_sorted = _nearest_neighbor_sort(attractions)

    logger.info("景点排序前 5：%s", [a["name"] for a in attrs_sorted[:5]])

    # ⭐ 4. 每天固定 7 个
    a_idx = 0
    day_schedules = []

    for d in range(1, days + 1):
        items: list[dict] = []

        # 早：早餐 + 景点 1
        if breakfast_pool:
            items.append({"poi_id": breakfast_pool.pop(0)["id"], "period": "morning"})
        elif main_pool:
            items.append({"poi_id": main_pool.pop(0)["id"], "period": "morning"})

        if a_idx < len(attrs_sorted):
            items.append({"poi_id": attrs_sorted[a_idx]["id"], "period": "morning"})
            a_idx += 1

        # 中：正餐
        if main_pool:
            items.append({"poi_id": main_pool.pop(0)["id"], "period": "noon"})

        # 下午：2 景点
        for _ in range(2):
            if a_idx < len(attrs_sorted):
                items.append({"poi_id": attrs_sorted[a_idx]["id"], "period": "afternoon"})
                a_idx += 1

        # 晚：正餐（或夜宵）+ 景点
        if main_pool:
            items.append({"poi_id": main_pool.pop(0)["id"], "period": "evening"})
        elif night_pool:
            items.append({"poi_id": night_pool.pop(0)["id"], "period": "evening"})

        if a_idx < len(attrs_sorted):
            items.append({"poi_id": attrs_sorted[a_idx]["id"], "period": "evening"})
            a_idx += 1

        day_schedules.append({"day": d, "items": items})

    logger.info("实际分配：%s 个/天", [len(d["items"]) for d in day_schedules])
    return day_schedules