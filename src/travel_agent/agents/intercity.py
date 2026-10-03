"""城际交通费估算 — 高德距离 × 系数，结果持久化缓存。

策略：
  1. 高德 geocode 拿两城坐标（缓存 30 天）
  2. 高德 driving 拿驾车距离（缓存 30 天）
  3. 距离 × 分档系数 = 单程估算票价
"""
import logging

import httpx

from ..config import settings
from ..cache import get as cache_get, set as cache_set, make_key

logger = logging.getLogger(__name__)

AMAP_BASE = "https://restapi.amap.com/v3"
CACHE_TTL = 86400 * 30


def get_intercity_cost(origin: str, dest: str) -> float:
    """返回单人单程估算票价（元）。失败返回 -1。"""
    if not origin or not dest or origin == dest:
        return 0.0

    key = make_key("intercity_v1", origin, dest)
    cached = cache_get(key, CACHE_TTL)
    if cached is not None:
        return float(cached)

    distance_km = _get_driving_distance(origin, dest)
    if distance_km <= 0:
        return -1.0

    price = _estimate_price(distance_km)
    cache_set(key, price)
    logger.info("城际估算：%s → %s = %.0fkm / %.0f元", origin, dest, distance_km, price)
    return price


def get_roundtrip_cost(origin: str, dest: str, companions: int) -> float:
    """往返总费用（全部人数）。"""
    single = get_intercity_cost(origin, dest)
    if single < 0:
        return -1.0
    return single * 2 * max(companions, 1)


def _estimate_price(distance_km: float) -> float:
    """按距离分档估算单程票价（元）。"""
    if distance_km < 300:
        # 短途：大巴/普速/短途高铁
        return 40 + distance_km * 0.35
    elif distance_km < 800:
        # 中短途：高铁二等座
        return distance_km * 0.42
    elif distance_km < 1500:
        # 中途：高铁/飞机混合
        return distance_km * 0.48
    else:
        # 长途：飞机经济舱
        return distance_km * 0.55


def _get_driving_distance(origin: str, dest: str) -> float:
    """高德驾车距离（公里）。失败返回 -1。"""
    if not settings.amap_key:
        return -1.0

    coord1 = _geocode(origin)
    coord2 = _geocode(dest)
    if not coord1 or not coord2:
        return -1.0

    url = f"{AMAP_BASE}/direction/driving"
    params = {
        "key": settings.amap_key,
        "origin": f"{coord1[0]},{coord1[1]}",
        "destination": f"{coord2[0]},{coord2[1]}",
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
            data = resp.json()
            if data.get("status") != "1":
                return -1.0
            paths = data.get("route", {}).get("paths", [])
            if not paths:
                return -1.0
            return float(paths[0].get("distance", 0)) / 1000.0
    except Exception as e:
        logger.warning("高德驾车距离失败 %s→%s: %s", origin, dest, e)
        return -1.0


def _geocode(city: str) -> tuple[float, float] | None:
    """城市名 → (lng, lat)。缓存 30 天。"""
    if not settings.amap_key:
        return None

    key = make_key("geocode_v1", city)
    cached = cache_get(key, CACHE_TTL)
    if cached:
        return (cached["lng"], cached["lat"])

    url = f"{AMAP_BASE}/geocode/geo"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params={"key": settings.amap_key, "address": city})
            data = resp.json()
            if data.get("status") != "1":
                return None
            geocodes = data.get("geocodes", [])
            if not geocodes:
                return None
            location = geocodes[0].get("location", "")
            if "," not in location:
                return None
            lng_s, lat_s = location.split(",")
            result = {"lng": float(lng_s), "lat": float(lat_s)}
            cache_set(key, result)
            return (result["lng"], result["lat"])
    except Exception as e:
        logger.warning("高德地理编码失败 %s: %s", city, e)
        return None