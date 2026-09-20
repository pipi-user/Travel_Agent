"""POI 池采集 v2 — 高德 POI + 偏好权重 + 预算硬过滤 + 行程预生成。

流程：
  1. 调用高德 POI 搜索获取原始景点/美食/酒店
  2. 图片处理链：高德图片 → Tavily 搜图 → 占位图
  3. 偏好标签权重排序
  4. 预算硬过滤（代码层，不依赖 LLM）
  5. 控制总量 25-35 条：景点 12-15，美食 10-12，酒店 4-6
  6. 规则引擎生成预划分行程 slots
  7. 返回 {pois, hotels, initial_itinerary}
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx

from ..config import settings
from ..cache import get as cache_get, set as cache_set, make_key
from ..schemas import POICard, HotelPOI
from .budget_filter import filter_by_budget
from .preference_scorer import score_by_preference
from .itinerary_planner import generate_initial_itinerary

logger = logging.getLogger(__name__)

POI_CACHE_TTL = 86400
PLACEHOLDER_IMG = "https://placehold.co/600x400/EEE/31343C?text=Travel&font=roboto"

AMAP_BASE = "https://restapi.amap.com/v3"

# 高德 POI 类型码
AMAP_TYPE_ATTRACTION = "110000"   # 风景名胜
AMAP_TYPE_FOOD = "050000"         # 餐饮服务
AMAP_TYPE_HOTEL = "100000"        # 住宿服务


def collect_pois_v2(
    city: str,
    budget: int,
    companions: int,
    days: int,
    intensity: str,
    preferences: list[str] | None = None,
) -> dict:
    """采集城市 POI，返回过滤后的 POI 池 + 预生成行程。"""
    prefs = preferences or []
    cache_key = make_key("poi_v2", city, budget, companions, days,
                         intensity, tuple(sorted(prefs)))
    cached = cache_get(cache_key, POI_CACHE_TTL)
    if cached:
        return cached

    # 1. 高德 POI 搜索
    raw_attractions = _amap_search(city, "景点 旅游", AMAP_TYPE_ATTRACTION, count=20)
    raw_foods = _amap_search(city, "美食 餐厅", AMAP_TYPE_FOOD, count=15)
    raw_hotels = _amap_search(city, "酒店 住宿", AMAP_TYPE_HOTEL, count=8)

    # 2. 转换为 POICard dict
    attractions = [_to_poi_dict(p, "attraction", city) for p in raw_attractions]
    foods = [_to_poi_dict(p, "food", city) for p in raw_foods]
    hotels_raw = [_to_poi_dict(p, "hotel", city) for p in raw_hotels]

    # 3. 图片补充
    with ThreadPoolExecutor(max_workers=8) as pool:
        attractions = list(pool.map(_ensure_image, attractions))
        foods = list(pool.map(_ensure_image, foods))
        hotels_raw = list(pool.map(_ensure_image, hotels_raw))

    # 4. 偏好标签权重排序
    all_pois = attractions + foods
    all_pois = score_by_preference(all_pois, prefs)

    # 拆分回来
    attractions = [p for p in all_pois if p["poi_type"] == "attraction"]
    foods = [p for p in all_pois if p["poi_type"] == "food"]

    # 5. 预算硬过滤
    hotels_for_budget = []
    for h in hotels_raw:
        night_price = h.get("cost", 0)
        h["single_night_price"] = night_price
        h["total_accommodation_cost"] = night_price * days
        h["per_person_accommodation"] = h["total_accommodation_cost"] / max(companions, 1)
        hotels_for_budget.append(h)

    all_for_budget = attractions + foods + hotels_for_budget
    filtered = filter_by_budget(all_for_budget, budget, days, companions)

    attractions = [p for p in filtered if p["poi_type"] == "attraction"]
    foods = [p for p in filtered if p["poi_type"] == "food"]
    hotels_filtered = [p for p in filtered if p["poi_type"] == "hotel"]

    # 6. 控制总量
    attractions = attractions[:15]
    foods = foods[:12]
    hotels_filtered = hotels_filtered[:6]

    # 确保最低数量
    if len(attractions) < 3:
        logger.warning("景点不足 3 个，实际 %d", len(attractions))
    if len(foods) < 3:
        logger.warning("美食不足 3 个，实际 %d", len(foods))

    # 7. 生成 HotelPOI 对象
    hotels: list[dict] = []
    for h in hotels_filtered:
        poi = POICard(**{k: v for k, v in h.items() if k in POICard.model_fields})
        hotel_poi = HotelPOI.from_poi(poi, days, companions)
        hotels.append(hotel_poi.model_dump())

    # 8. 生成 POICard 列表
    pois: list[dict] = []
    for p in attractions + foods:
        card = POICard(**{k: v for k, v in p.items() if k in POICard.model_fields})
        pois.append(card.model_dump())

    # 9. 生成预划分行程
    initial_itinerary = generate_initial_itinerary(
        attractions=attractions,
        foods=foods,
        days=days,
        intensity=intensity,
    )

    result = {
        "pois": pois,
        "hotels": hotels,
        "initial_itinerary": initial_itinerary,
    }
    cache_set(cache_key, result)
    return result


# ========== 高德 POI 搜索 ==========

def _amap_search(city: str, keywords: str, type_code: str, count: int = 10) -> list[dict]:
    """调用高德 POI 搜索接口。"""
    if not settings.amap_key:
        logger.warning("未配置高德 API Key，返回空结果")
        return []

    url = f"{AMAP_BASE}/place/text"
    params = {
        "key": settings.amap_key,
        "keywords": keywords,
        "city": city,
        "types": type_code,
        "offset": min(count, 25),
        "page": 1,
        "extensions": "all",
    }
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


def _to_poi_dict(raw: dict, poi_type: str, city: str) -> dict:
    """将高德原始 POI 转为内部 dict。"""
    name = raw.get("name", "")
    address = raw.get("address", "")
    if isinstance(address, list):
        address = "".join(address)

    # 坐标
    location = raw.get("location", "")
    lng, lat = 0.0, 0.0
    if location and "," in location:
        try:
            lng_s, lat_s = location.split(",")
            lng, lat = float(lng_s), float(lat_s)
        except (ValueError, TypeError):
            pass

    # 评分
    rating = raw.get("biz_ext", {}).get("rating", "0")
    if isinstance(rating, list):
        rating = "0"
    try:
        score = float(rating) if rating else 0.0
        if score > 5:
            score = score / 2  # 高德有些评分是 10 分制
    except (ValueError, TypeError):
        score = 0.0

    # 花费
    cost_raw = raw.get("biz_ext", {}).get("cost", "0")
    if isinstance(cost_raw, list):
        cost_raw = "0"
    try:
        cost = float(re.findall(r"[\d.]+", str(cost_raw).replace(",", ""))[0]) if cost_raw else 0.0
    except (IndexError, ValueError, TypeError):
        cost = 0.0

    # 图片
    photos = raw.get("photos", [])
    image_url = photos[0].get("url", "") if photos else ""

    # 标签
    type_name = raw.get("type", "")
    tags = _extract_tags(type_name, raw.get("biz_ext", {}))

    poi_id = f"{poi_type[:3]}_{abs(hash(f'{city}:{poi_type}:{name}')) % 10**9}"

    return {
        "id": poi_id,
        "name": name,
        "poi_type": poi_type,
        "score": score,
        "desc": raw.get("address", "") or f"{city}{name}",
        "cost": cost,
        "duration": _estimate_duration(poi_type, cost),
        "lat": lat,
        "lng": lng,
        "image_url": image_url,
        "tags": tags,
        "address": address or f"{city}{name}",
    }


def _extract_tags(type_name: str, biz_ext: dict) -> list[str]:
    """从高德类型名和 biz_ext 提取标签。"""
    tags = []
    if type_name:
        parts = type_name.split(";")
        for p in parts:
            p = p.strip()
            if p and len(p) < 10:
                tags.append(p)
    # 取前 3 个标签
    return tags[:3]


def _estimate_duration(poi_type: str, cost: float) -> int:
    """根据类型和花费估算停留时间（分钟）。"""
    if poi_type == "attraction":
        return 120 if cost > 50 else 90
    elif poi_type == "food":
        return 60
    elif poi_type == "hotel":
        return 0  # 酒店不占行程时间
    return 90


def _ensure_image(poi: dict) -> dict:
    """确保 POI 有图片，没有则用占位图。"""
    if poi.get("image_url"):
        return poi
    # 尝试 Tavily 搜图
    img = _tavily_image(poi.get("name", ""), poi.get("address", ""))
    poi["image_url"] = img or PLACEHOLDER_IMG
    return poi


def _tavily_image(name: str, city: str) -> str:
    """Tavily 搜图（带缓存）。"""
    if not settings.tavily_api_key:
        return ""
    key = make_key("tavily_img_v2", city, name)
    hit = cache_get(key, POI_CACHE_TTL)
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
