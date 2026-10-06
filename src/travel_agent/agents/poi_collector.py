"""POI 池采集 v4 — 城市池 + 用户级过滤分离。

核心优化：
  1. 城市池（高德采集 + LLM 打标 + 补图）只按城市缓存，30 天有效
  2. 用户参数（预算/人数/天数/偏好）实时过滤，毫秒级
  3. 缓存持久化到 SQLite，重启不丢
"""
import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from ..config import settings
from ..cache import get as cache_get, set as cache_set, make_key
from ..schemas import POICard, HotelPOI
from ..llm import get_llm
from .budget_filter import filter_by_budget
from .preference_scorer import score_by_preference
from .itinerary_planner import generate_initial_itinerary

logger = logging.getLogger(__name__)

# ⭐ 缓存 TTL
POI_POOL_TTL = 86400 * 30      # 城市 POI 池：30 天
TAG_CACHE_TTL = 86400 * 7      # LLM 打标：7 天
IMG_CACHE_TTL = 86400 * 30     # 图片 URL：30 天

# 池版本号（改采集逻辑时递增，强制刷新旧缓存）
POOL_VERSION = "v1"

PLACEHOLDER_IMG = "https://placehold.co/600x400/EEE/31343C?text=Travel&font=roboto"

AMAP_BASE = "https://restapi.amap.com/v3"

AMAP_TYPE_ATTRACTION = "110000"
AMAP_TYPE_FOOD = "050000"
AMAP_TYPE_HOTEL = "100000"

AMAP_TYPE_MAP = {
    "attraction": AMAP_TYPE_ATTRACTION,
    "food": AMAP_TYPE_FOOD,
    "hotel": AMAP_TYPE_HOTEL,
}

AMAP_KEYWORDS = {
    "attraction": [
        "景点", "公园", "博物馆", "地标", "寺庙", "古镇",
        "纪念馆", "艺术馆", "景区", "植物园",
    ],
    "food": [
        "餐厅", "小吃", "火锅", "海鲜", "早茶", "夜宵",
        "烧烤", "本地菜", "特色菜", "甜品",
    ],
    "hotel": [
        "酒店", "民宿", "青旅", "公寓", "客栈",
        "度假村", "宾馆", "招待所", "旅馆",
    ],
}

AMAP_PAGES_PER_KEYWORD = 2
AMAP_PAGE_SIZE = 25
AMAP_SLEEP = 0.4

# ══════════════════════════════════════════════════════
# 酒店费用估算（高德不返回酒店房价，按类型 + 城市估算）
# ══════════════════════════════════════════════════════

# 一线/新一线城市（酒店价格偏高）
_TIER1_CITIES = {
    "北京", "上海", "广州", "深圳", "成都", "杭州", "重庆",
    "西安", "南京", "苏州", "武汉", "天津", "长沙", "郑州",
    "东莞", "佛山", "青岛", "昆明", "宁波", "无锡",
}

# 旅游热门城市（旺季溢价）
_HOT_CITIES = {"三亚", "丽江", "大理", "厦门", "拉萨", "西双版纳"}


def _estimate_hotel_price(hotel: dict, city: str) -> float:
    """根据酒店名称/标签 + 城市等级估算单晚房价（元）。"""
    name = hotel.get("name", "")
    tags = hotel.get("tags", [])
    tag_str = " ".join(tags)
    combined = name + tag_str

    # ── 按类型匹配基础价格 ──
    if any(kw in combined for kw in ["五星", "豪华", "度假", "国际", "万豪", "希尔顿", "洲际", "丽思"]):
        base = 800
    elif any(kw in combined for kw in ["精品", "设计", "boutique"]):
        base = 500
    elif any(kw in combined for kw in ["民宿", "客栈", "公寓"]):
        base = 280
    elif any(kw in combined for kw in ["青旅", "旅舍", " hostel"]):
        base = 80
    elif any(kw in combined for kw in ["连锁", "快捷", "如家", "汉庭", "7天", "锦江之星", "全季", "亚朵"]):
        base = 220
    elif any(kw in combined for kw in ["温泉", "度假村"]):
        base = 600
    else:
        base = 350  # 普通酒店/宾馆

    # ── 城市系数 ──
    if city in _HOT_CITIES:
        base = int(base * 1.3)
    elif city in _TIER1_CITIES:
        base = int(base * 1.15)

    return float(base)


MAX_ATTRACTIONS = 100
MAX_FOODS = 100
MAX_HOTELS = 50

TAG_BATCH_SIZE = 8
TAG_CONCURRENCY = 3


# ══════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════

def collect_pois_v2(
    city: str,
    budget: int,
    companions: int,
    days: int,
    intensity: str,
    preferences: list[str] | None = None,
) -> dict:
    """采集城市 POI + 应用用户约束。

    - 城市池：按 city 缓存，30 天有效
    - 用户过滤：每次实时，毫秒级
    """
    prefs = preferences or []

    # 1. ⭐ 城市池（慢，只按城市缓存）
    pool = _get_or_build_city_pool(city)

    # 2. ⭐ 用户级过滤（快，每次实时）
    return _apply_user_constraints(
        pool, city, budget, companions, days, intensity, prefs,
    )


def _get_or_build_city_pool(city: str) -> dict:
    """查城市池缓存，没有就采集。"""
    key = make_key("city_pool", POOL_VERSION, city)
    cached = cache_get(key, POI_POOL_TTL)
    if cached:
        logger.info("城市池缓存命中：%s", city)
        return cached

    logger.info("首次采集城市池：%s", city)
    t0 = time.time()
    pool = _collect_city_pool(city)
    cache_set(key, pool)
    logger.info("城市池采集完成：%s（耗时 %.1fs）", city, time.time() - t0)
    return pool


def _collect_city_pool(city: str) -> dict:
    """慢采集：高德 + 去重 + LLM 打标 + 补图。"""
    # 高德
    raw_attractions = _amap_search_multi(city, "attraction")
    raw_foods = _amap_search_multi(city, "food")
    raw_hotels = _amap_search_multi(city, "hotel")

    logger.info(
        "%s 高德原始：景点 %d / 美食 %d / 酒店 %d",
        city, len(raw_attractions), len(raw_foods), len(raw_hotels),
    )

    # 转 dict
    attractions = [_to_poi_dict(p, "attraction", city) for p in raw_attractions]
    foods = [_to_poi_dict(p, "food", city) for p in raw_foods]
    hotels_raw = [_to_poi_dict(p, "hotel", city) for p in raw_hotels]

    # 酒店费用估算：高德不返回酒店房价，按类型 + 城市估算
    for h in hotels_raw:
        if h.get("cost", 0) == 0:
            h["cost"] = _estimate_hotel_price(h, city)

    # 去重
    attractions = _dedup_by_location(attractions)
    foods = _dedup_by_location(foods)
    hotels_raw = _dedup_by_location(hotels_raw)

    # LLM 打标
    attractions = _batch_enrich_tags(attractions, city)
    foods = _batch_enrich_tags(foods, city)

    # 补图
    with ThreadPoolExecutor(max_workers=10) as pool:
        attractions = list(pool.map(_ensure_image, attractions))
        foods = list(pool.map(_ensure_image, foods))
        hotels_raw = list(pool.map(_ensure_image, hotels_raw))

    return {
        "attractions": attractions,
        "foods": foods,
        "hotels_raw": hotels_raw,
        "collected_at": time.time(),
    }


def _apply_user_constraints(
    pool: dict, city: str,
    budget: int, companions: int, days: int,
    intensity: str, prefs: list[str],
) -> dict:
    """快过滤：偏好排序 + 预算过滤 + 分天。"""
    # ⭐ 浅拷贝，防止污染缓存
    attractions = [dict(p) for p in pool["attractions"]]
    foods = [dict(p) for p in pool["foods"]]
    hotels_raw = [dict(p) for p in pool["hotels_raw"]]

    # 偏好排序
    all_pois = attractions + foods
    all_pois = score_by_preference(all_pois, prefs)
    attractions = [p for p in all_pois if p["poi_type"] == "attraction"]
    foods = [p for p in all_pois if p["poi_type"] == "food"]

    # 酒店费用计算
    hotels_for_budget = []
    for h in hotels_raw:
        night_price = h.get("cost", 0)
        h["single_night_price"] = night_price
        h["total_accommodation_cost"] = night_price * days
        h["per_person_accommodation"] = h["total_accommodation_cost"] / max(companions, 1)
        hotels_for_budget.append(h)

    # 预算过滤
    all_for_budget = attractions + foods + hotels_for_budget
    filtered = filter_by_budget(all_for_budget, budget, days, companions)
    attractions = [p for p in filtered if p["poi_type"] == "attraction"]
    foods = [p for p in filtered if p["poi_type"] == "food"]
    hotels_filtered = [p for p in filtered if p["poi_type"] == "hotel"]

    # 截断
    attractions = attractions[:MAX_ATTRACTIONS]
    foods = foods[:MAX_FOODS]
    hotels_filtered = hotels_filtered[:MAX_HOTELS]

    logger.info(
        "%s 过滤后：景点 %d / 美食 %d / 酒店 %d",
        city, len(attractions), len(foods), len(hotels_filtered),
    )

    # HotelPOI
    hotels: list[dict] = []
    for h in hotels_filtered:
        # 兜底：如果缓存中 cost=0，重新估算
        if h.get("cost", 0) == 0:
            h["cost"] = _estimate_hotel_price(h, city)
        poi = POICard(**{k: v for k, v in h.items() if k in POICard.model_fields})
        hotel_poi = HotelPOI.from_poi(poi, days, companions)
        hotels.append(hotel_poi.model_dump())

    # POICard
    pois: list[dict] = []
    for p in attractions + foods:
        card = POICard(**{k: v for k, v in p.items() if k in POICard.model_fields})
        pois.append(card.model_dump())

    # 预生成行程（传入第一个酒店位置作为锚点）
    hotel_lat = hotels[0].get("lat") if hotels else None
    hotel_lng = hotels[0].get("lng") if hotels else None
    initial_itinerary = generate_initial_itinerary(
        attractions=attractions,
        foods=foods,
        days=days,
        intensity=intensity,
        hotel_lat=hotel_lat,
        hotel_lng=hotel_lng,
    )

    return {
        "pois": pois,
        "hotels": hotels,
        "initial_itinerary": initial_itinerary,
    }


# ══════════════════════════════════════════════════════
# 高德采集
# ══════════════════════════════════════════════════════

def _amap_search_multi(city: str, poi_type: str) -> list[dict]:
    keywords = AMAP_KEYWORDS.get(poi_type, [])
    type_code = "" if poi_type == "hotel" else AMAP_TYPE_MAP[poi_type]
    seen_ids: set[str] = set()
    results: list[dict] = []

    for kw in keywords:
        for page in range(1, AMAP_PAGES_PER_KEYWORD + 1):
            batch = _amap_search(city, kw, type_code, page=page)
            if not batch:
                break

            for p in batch:
                pid = p.get("id", "")
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)
                results.append(p)

            if len(batch) < AMAP_PAGE_SIZE:
                break
            time.sleep(AMAP_SLEEP)

    return results


def _amap_search(city: str, keywords: str, type_code: str, page: int = 1) -> list[dict]:
    if not settings.amap_key:
        logger.warning("未配置高德 API Key，返回空结果")
        return []

    url = f"{AMAP_BASE}/place/text"
    params = {
        "key": settings.amap_key,
        "keywords": keywords,
        "city": city,
        "offset": AMAP_PAGE_SIZE,
        "page": page,
        "extensions": "all",
    }
    if type_code:
        params["types"] = type_code

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
            data = resp.json()
            if data.get("status") != "1":
                logger.error("高德 API 错误：%s", data.get("info"))
                return []
            return data.get("pois", [])
    except Exception as e:
        logger.error("高德搜索失败：%s", e)
        return []


# ══════════════════════════════════════════════════════
# POI 转换
# ══════════════════════════════════════════════════════

def _to_poi_dict(raw: dict, poi_type: str, city: str) -> dict:
    name = raw.get("name", "")
    address = raw.get("address", "")
    if isinstance(address, list):
        address = "".join(address)

    location = raw.get("location", "")
    lng, lat = 0.0, 0.0
    if location and "," in location:
        try:
            lng_s, lat_s = location.split(",")
            lng, lat = float(lng_s), float(lat_s)
        except (ValueError, TypeError):
            pass

    rating = raw.get("biz_ext", {}).get("rating", "0")
    if isinstance(rating, list):
        rating = "0"
    try:
        score = float(rating) if rating else 0.0
        if score > 5:
            score = score / 2
    except (ValueError, TypeError):
        score = 0.0

    cost_raw = raw.get("biz_ext", {}).get("cost", "0")
    if isinstance(cost_raw, list):
        cost_raw = "0"
    try:
        cost = float(re.findall(r"[\d.]+", str(cost_raw).replace(",", ""))[0]) if cost_raw else 0.0
    except (IndexError, ValueError, TypeError):
        cost = 0.0

    photos = raw.get("photos", [])
    image_url = photos[0].get("url", "") if photos else ""

    type_name = raw.get("type", "")
    base_tags = _extract_tags(type_name)

    poi_id = _make_stable_id(city, poi_type, name)

    return {
        "id": poi_id,
        "name": name,
        "poi_type": poi_type,
        "score": score,
        "desc": address or f"{city}{name}",
        "cost": cost,
        "duration": _estimate_duration(poi_type, cost),
        "lat": lat,
        "lng": lng,
        "image_url": image_url,
        "tags": base_tags,
        "address": address or f"{city}{name}",
    }


def _make_stable_id(city: str, poi_type: str, name: str) -> str:
    raw = f"{city}:{poi_type}:{name}".encode("utf-8")
    h = int(hashlib.md5(raw).hexdigest()[:8], 16)
    return f"{poi_type[:3]}_{h % 10**9}"


def _dedup_by_location(pois: list[dict]) -> list[dict]:
    seen: set = set()
    result: list[dict] = []
    for p in pois:
        lat, lng = p.get("lat", 0), p.get("lng", 0)
        if lat and lng:
            key = (p["name"], round(lat, 4), round(lng, 4))
        else:
            key = p["name"]
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def _extract_tags(type_name: str) -> list[str]:
    tags = []
    if type_name:
        for p in type_name.split(";"):
            p = p.strip()
            if p and len(p) < 10:
                tags.append(p)
    return tags[:3]


def _estimate_duration(poi_type: str, cost: float) -> int:
    if poi_type == "attraction":
        return 120 if cost > 50 else 90
    elif poi_type == "food":
        return 60
    elif poi_type == "hotel":
        return 0
    return 90


# ══════════════════════════════════════════════════════
# LLM 批量打标
# ══════════════════════════════════════════════════════

def _batch_enrich_tags(pois: list[dict], city: str) -> list[dict]:
    if not pois:
        return []

    enriched: list[dict] = []
    to_process: list[dict] = []

    for p in pois:
        cache_key = make_key("tags_v1", city, p["name"], p.get("address", ""))
        cached = cache_get(cache_key, TAG_CACHE_TTL)
        if cached:
            p["tags"] = cached.get("tags") or p.get("tags", [])
            p["desc"] = cached.get("desc") or p.get("desc", "")
            enriched.append(p)
        else:
            to_process.append(p)

    if not to_process:
        logger.info("LLM 打标：全部命中缓存（%d 条）", len(enriched))
        return enriched

    batches = [
        to_process[i:i + TAG_BATCH_SIZE]
        for i in range(0, len(to_process), TAG_BATCH_SIZE)
    ]
    logger.info(
        "LLM 打标：%d 条待处理，分 %d 批（缓存命中 %d 条）",
        len(to_process), len(batches), len(enriched),
    )

    with ThreadPoolExecutor(max_workers=TAG_CONCURRENCY) as pool:
        futures = {
            pool.submit(_llm_tag_batch, batch, city): batch
            for batch in batches
        }
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                enriched.extend(fut.result())
            except Exception as e:
                logger.warning("批次打标失败：%s", e)
                enriched.extend(batch)

    return enriched


def _llm_tag_batch(batch: list[dict], city: str) -> list[dict]:
    llm = get_llm(json_mode=True)

    items = [
        {"idx": i, "name": p["name"], "poi_type": p["poi_type"], "address": p.get("address", "")}
        for i, p in enumerate(batch)
    ]

    prompt = f"""给以下 {city} 的 POI 打标签和写简介。

输入：
{json.dumps(items, ensure_ascii=False)}

输出严格 JSON 数组，每元素：
{{"idx": 0, "tags": ["标签1","标签2","标签3"], "desc": "20-40字简介"}}

标签优先从[美食/自然/历史/购物/摄影/冒险/休闲/人文/老字号/网红/小众/博物馆/公园/寺庙/火锅/海鲜/小吃]里选，3-5个。
简介基于名称+类型合理描述，不要编造具体事实。信息不足写"XX的一处XX"。
只输出 JSON，无解释。"""

    try:
        resp = llm.invoke(prompt)
        content = resp.content.strip()
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()

        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            content = content[start:end + 1]

        data = json.loads(content)
        if not isinstance(data, list):
            data = [data]

        tag_map: dict[int, dict] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("idx", -1))
            except (ValueError, TypeError):
                continue
            if idx >= 0:
                tag_map[idx] = item

        for i, p in enumerate(batch):
            tag_data = tag_map.get(i, {})
            tags = tag_data.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tags = [str(t).strip() for t in tags if t][:5]

            desc = tag_data.get("desc", "")
            if not isinstance(desc, str):
                desc = ""
            desc = desc.strip()

            p["tags"] = tags or p.get("tags", [])
            p["desc"] = desc or p.get("desc", "")

            cache_key = make_key("tags_v1", city, p["name"], p.get("address", ""))
            cache_set(cache_key, {"tags": p["tags"], "desc": p["desc"]})

        return batch

    except Exception as e:
        logger.warning("LLM 打标失败（batch size=%d）：%s", len(batch), e)
        for p in batch:
            p.setdefault("tags", [])
            p.setdefault("desc", "")
        return batch


# ══════════════════════════════════════════════════════
# 图片处理
# ══════════════════════════════════════════════════════

def _ensure_image(poi: dict) -> dict:
    if poi.get("image_url"):
        return poi
    img = _tavily_image(poi.get("name", ""), poi.get("address", ""))
    poi["image_url"] = img or PLACEHOLDER_IMG
    return poi


def _tavily_image(name: str, city: str) -> str:
    if not settings.tavily_api_key:
        return ""
    key = make_key("tavily_img_v3", city, name)
    hit = cache_get(key, IMG_CACHE_TTL)
    if hit is not None:
        return hit
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        r = client.search(
            query=f"{city} {name} 风景",
            include_images=True,
            max_results=3,
            search_depth="basic",
        )
        imgs = r.get("images") or []
        result = imgs[0] if imgs else ""
        cache_set(key, result)
        return result
    except Exception:
        cache_set(key, "")
        return ""