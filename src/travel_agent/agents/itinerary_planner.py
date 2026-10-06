"""行程编排 v7 — 评分优先 + 地理就近匹配 + 固定结构。

每天固定 7 个：
  早：1 餐 + 1 景点
  中：1 餐
  下午：2 景点
  晚：1 餐 + 1 景点

排序原则：
  1. 景点按评分降序 → 去同质 → 地理聚集（最近邻）
  2. 餐食按「距离景点近 + 评分高」综合匹配，不再纯按评分
  3. 早餐匹配早上景点，正餐匹配下午/晚上景点附近
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


# 必须安排在晚上的景点关键词
EVENING_KW = ["灯光秀", "夜景", "夜游", "晚会", "演出", "表演", "秀", "夜市", "夜间"]
# 适合早上的景点关键词
MORNING_KW = ["早市", "晨练", "日出", "早餐街", "早茶"]


def _preferred_period(poi: dict) -> str:
    """根据景点名称/标签判断最适合的时段。"""
    name = poi.get("name", "")
    tags = poi.get("tags", []) or []
    text = name + " " + " ".join(tags)

    if any(kw in text for kw in EVENING_KW):
        return "evening"
    if any(kw in text for kw in MORNING_KW):
        return "morning"
    return "any"  # 任意时段都可以


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


def _find_nearest_food(
    food_pool: list[dict],
    anchor_pois: list[dict],
    max_distance_km: float = 5.0,
) -> tuple[dict | None, list[dict]]:
    """从食物池中找离锚点景点最近的餐厅。

    综合评分 = 距离分(越近越高) + 排名分(原评分排序)。
    返回 (选中的餐厅, 剩余池)。
    """
    if not food_pool or not anchor_pois:
        return (food_pool.pop(0) if food_pool else None, food_pool)

    # 计算每个食物到所有锚点景点的最短距离
    scored_foods = []
    for i, f in enumerate(food_pool):
        min_dist = min(_haversine(f, anchor) for anchor in anchor_pois)
        # 距离分：5km 内线性衰减，5km 外给最低分
        dist_score = max(0, 1.0 - min_dist / max_distance_km)
        # 排名分：原池顺序越靠前分越高（已按特色评分排序）
        rank_score = 1.0 - (i / max(len(food_pool), 1))
        # 综合：特色评分 70%，距离 30%（特色为主，位置为辅）
        combined = rank_score * 0.7 + dist_score * 0.3
        scored_foods.append((combined, i, f))

    # 选综合分最高的
    scored_foods.sort(key=lambda x: x[0], reverse=True)
    best_score, best_idx, best_food = scored_foods[0]

    remaining = [f for j, f in enumerate(food_pool) if j != best_idx]
    return best_food, remaining


def generate_initial_itinerary(
    attractions: list[dict],
    foods: list[dict],
    days: int,
    intensity: str,
    hotel_lat: float | None = None,
    hotel_lng: float | None = None,
) -> list[dict]:
    """生成行程。每天固定 7 个：3 食 + 4 景。

    核心改进：餐食按景点地理位置就近匹配。
    可选：传入酒店位置，以酒店为锚点优化行程。
    """
    days = max(days, 1)

    if not attractions and not foods:
        return [{"day": d, "items": []} for d in range(1, days + 1)]

    # ⭐ 1. 分池（不排序，后续按地理匹配）
    breakfast_pool = [f for f in foods if _classify_food(f.get("name", "")) == "breakfast"]
    night_pool = [f for f in foods if _classify_food(f.get("name", "")) == "night"]
    main_pool = [f for f in foods if _classify_food(f.get("name", "")) == "main"]

    # 池内先按评分降序（作为排名分的基础）
    breakfast_pool.sort(key=_rank_score, reverse=True)
    night_pool.sort(key=_rank_score, reverse=True)
    main_pool.sort(key=_rank_score, reverse=True)

    logger.info(
        "食物池：早 %d / 正 %d / 夜 %d",
        len(breakfast_pool), len(main_pool), len(night_pool),
    )

    # ⭐ 2. 景点按评分降序 → 去同质 → 地理聚集
    attractions = sorted(attractions, key=_rank_score, reverse=True)
    attractions = _dedup_by_tag(attractions, max_per_tag=max(2, days))

    # ⭐ 2.3 如果有酒店位置，优先把离酒店近的景点排在前面
    if hotel_lat and hotel_lng:
        hotel_poi = {"lat": hotel_lat, "lng": hotel_lng}
        # 计算每个景点到酒店的距离
        for a in attractions:
            a["_dist_to_hotel"] = _haversine(a, hotel_poi)
        # 按距离排序（近的优先），但保留评分权重
        attractions.sort(key=lambda a: (a.get("_dist_to_hotel", 999), -_rank_score(a)))
        logger.info("已按酒店位置重排序景点（前 3 离酒店最近）")

    attrs_sorted = _nearest_neighbor_sort(attractions)

    # ⭐ 2.5 按时段偏好分类
    evening_attrs = [a for a in attrs_sorted if _preferred_period(a) == "evening"]
    morning_attrs = [a for a in attrs_sorted if _preferred_period(a) == "morning"]
    any_attrs = [a for a in attrs_sorted if _preferred_period(a) == "any"]

    logger.info("景点排序前 5：%s", [a["name"] for a in attrs_sorted[:5]])
    logger.info("时段分类：早 %d / 晚 %d / 任意 %d", len(morning_attrs), len(evening_attrs), len(any_attrs))

    #  3. 按天分配：按时段偏好分配景点，餐食就近匹配
    m_idx, e_idx, any_idx = 0, 0, 0
    day_schedules = []

    def _take_morning():
        """取早上景点：优先 morning_attrs，其次 any_attrs（不取 evening_attrs）。"""
        nonlocal m_idx, any_idx
        if m_idx < len(morning_attrs):
            a = morning_attrs[m_idx]; m_idx += 1; return a
        if any_idx < len(any_attrs):
            a = any_attrs[any_idx]; any_idx += 1; return a
        return None

    def _take_afternoon():
        """取下午景点：优先 any_attrs，其次 morning_attrs（不取 evening_attrs）。"""
        nonlocal m_idx, any_idx
        if any_idx < len(any_attrs):
            a = any_attrs[any_idx]; any_idx += 1; return a
        if m_idx < len(morning_attrs):
            a = morning_attrs[m_idx]; m_idx += 1; return a
        return None

    def _take_evening():
        """取晚上景点：优先 evening_attrs，其次 any_attrs（不取 morning_attrs）。"""
        nonlocal e_idx, any_idx
        if e_idx < len(evening_attrs):
            a = evening_attrs[e_idx]; e_idx += 1; return a
        if any_idx < len(any_attrs):
            a = any_attrs[any_idx]; any_idx += 1; return a
        return None

    for d in range(1, days + 1):
        items: list[dict] = []

        # ── 早：先定景点，再匹配附近早餐 
        morning_attraction = _take_morning()
        if morning_attraction:
            items.append({"poi_id": morning_attraction["id"], "period": "morning"})
            # 早餐匹配早上景点附近
            if breakfast_pool:
                chosen, breakfast_pool = _find_nearest_food(breakfast_pool, [morning_attraction])
                if chosen:
                    items.insert(0, {"poi_id": chosen["id"], "period": "morning"})
            elif main_pool:
                chosen, main_pool = _find_nearest_food(main_pool, [morning_attraction])
                if chosen:
                    items.insert(0, {"poi_id": chosen["id"], "period": "morning"})
        else:
            # 没景点了，直接取评分最高的
            if breakfast_pool:
                items.insert(0, {"poi_id": breakfast_pool.pop(0)["id"], "period": "morning"})
            elif main_pool:
                items.insert(0, {"poi_id": main_pool.pop(0)["id"], "period": "morning"})

        # ── 中：匹配下午第一个景点附近 ──
        afternoon_first = _take_afternoon()
        if main_pool:
            if afternoon_first:
                chosen, main_pool = _find_nearest_food(main_pool, [afternoon_first])
            else:
                chosen = main_pool.pop(0)
            if chosen:
                items.append({"poi_id": chosen["id"], "period": "noon"})

        # ── 下午：再取 1 景点 ──
        afternoon_anchors = []
        afternoon_second = _take_afternoon()
        if afternoon_first:
            afternoon_anchors.append(afternoon_first)
            items.append({"poi_id": afternoon_first["id"], "period": "afternoon"})
        if afternoon_second:
            afternoon_anchors.append(afternoon_second)
            items.append({"poi_id": afternoon_second["id"], "period": "afternoon"})

        # ── 晚：优先安排 evening_attrs ──
        evening_attraction = _take_evening()
        if evening_attraction:
            items.append({"poi_id": evening_attraction["id"], "period": "evening"})

        # 晚餐锚点 = 晚上景点 + 下午景点（取最近的）
        dinner_anchors = [a for a in [evening_attraction] + afternoon_anchors if a]
        if dinner_anchors:
            if main_pool:
                chosen, main_pool = _find_nearest_food(main_pool, dinner_anchors)
                if chosen:
                    items.append({"poi_id": chosen["id"], "period": "evening"})
            elif night_pool:
                chosen, night_pool = _find_nearest_food(night_pool, dinner_anchors)
                if chosen:
                    items.append({"poi_id": chosen["id"], "period": "evening"})
        else:
            if main_pool:
                items.append({"poi_id": main_pool.pop(0)["id"], "period": "evening"})
            elif night_pool:
                items.append({"poi_id": night_pool.pop(0)["id"], "period": "evening"})

        day_schedules.append({"day": d, "items": items})


    logger.info("实际分配：%s 个/天", [len(d["items"]) for d in day_schedules])
    return day_schedules