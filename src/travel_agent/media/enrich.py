"""给 POI 补充图片、链接、坐标。

优化点：
  1. LLM 已返回的 image_url 直接用，**不再调 Tavily**
  2. 只有缺图时才搜，且结果按 (city,name) 缓存
  3. Tavily 搜图并发执行
"""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from ..cache import get as cache_get, set as cache_set, make_key
from ..config import settings

PLACEHOLDER = "https://placehold.co/600x400/EEE/31343C?text={name}&font=roboto"
TAVILY_TTL = 86400      # 搜图缓存 1 天


def enrich_poi(
    name: str,
    city: str = "",
    cover: str = "",          # ⭐ 新增：LLM 返回的 image_url
    images: list[str] | None = None,
    lat: float = 0.0,
    lng: float = 0.0,
    detail_url: str = "",
) -> dict:
    """返回 POICard 需要的富化字段。永不抛异常、永不同步调 Tavily。"""
    images = [u for u in (images or []) if u]
    # ⭐ LLM 已给图 → 直接用，不走 Tavily
    if not cover and images:
        cover = images[0]

    # 缺图时才需要异步补（本函数只做占位，不阻塞）
    if not cover:
        cover = _tavily_image_cached(name, city) or PLACEHOLDER.format(name=quote(name[:20]))
    if not images:
        images = [cover]

    if not detail_url:
        detail_url = _amap_search_url(name, city)

    return {
        "cover_image": cover,
        "images": images,
        "detail_url": detail_url,
        "map_url": _amap_marker_url(name, lat, lng, city),
        "lat": lat,
        "lng": lng,
    }


def enrich_batch(
    items: list[dict],
    city: str,
    type_: str,
    max_workers: int = 8,
) -> list[dict]:
    """批量富化：并发生成 POICard。"""
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda x: _to_card(x, city, type_), items))


# ---------- 内部 ----------

def _to_card(item: dict, city: str, type_: str) -> dict:
    from ..schemas import POICard      # 延迟导入避免循环
    name = item.get("name", "")
    # ⭐ 关键：把 LLM 返回的 image_url / lng / lat 传进去
    enriched = enrich_poi(
        name=name,
        city=city,
        cover=item.get("image_url") or item.get("cover_image") or "",
        images=item.get("images") or [],
        lat=float(item.get("lat") or 0),
        lng=float(item.get("lng") or 0),
    )
    poi_id = f"{type_[:3]}_{abs(hash(f'{city}:{type_}:{name}')) % 10**9}"
    return POICard(
        id=poi_id,
        type=type_,
        name=name,
        city=city,
        address=item.get("address", ""),
        rating=str(item.get("rating", "暂无")),
        tags=item.get("tags", []) or [],
        cost=str(item.get("cost", "暂无")),
        duration_min=int(item.get("duration_min") or 90),
        description=item.get("description", ""),
        reason=item.get("reason", ""),
        open_hours=item.get("open_hours", ""),
        **enriched,
    ).model_dump()


def _tavily_image_cached(name: str, city: str) -> str:
    """带缓存的 Tavily 搜图。只在没图时用。"""
    if not settings.tavily_api_key:
        return ""
    key = make_key("tavily_img", city, name)
    hit = cache_get(key, TAVILY_TTL)
    if hit is not None:
        return hit

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        r = client.search(
            query=f"{city} {name}",
            include_images=True,
            max_results=3,
            search_depth="basic",
        )
        imgs = r.get("images") or []
        result = imgs[0] if imgs else ""
        cache_set(key, result)
        return result
    except Exception:
        cache_set(key, "")   # 失败也缓存，避免重复打
        return ""


def _amap_search_url(name: str, city: str) -> str:
    return f"https://www.amap.com/search?query={quote(name)}&city={quote(city)}"


def _amap_marker_url(name: str, lat: float, lng: float, city: str) -> str:
    if lat and lng:
        return f"https://uri.amap.com/marker?position={lng},{lat}&name={quote(name)}"
    return _amap_search_url(name, city)