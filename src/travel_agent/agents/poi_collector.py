"""POI 池采集 v3 — 多关键词 × 翻页 + LLM 打标 + 偏好排序 + 预算过滤。

流程：
  1. 高德多关键词 × 多页搜索（景点/美食/酒店）
  2. 按 (name, 坐标) 去重
  3. LLM 批量打标（tags + desc），带缓存
  4. 图片补充（高德图 → Tavily → 占位图），并发
  5. 偏好标签权重排序
  6. 预算硬过滤（代码层，不依赖 LLM）
  7. 规则引擎生成预划分行程
  8. 返回 {pois, hotels, initial_itinerary}

性能提示：
  - 首次采集一个城市约 2-3 分钟（高德翻页 + LLM 打标 + 补图）
  - 之后命中缓存，秒级返回
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

# 缓存 TTL
POI_CACHE_TTL = 86400          # POI 池：1 天
TAG_CACHE_TTL = 86400 * 7      # LLM 打标：7 天
IMG_CACHE_TTL = 86400          # Tavily 图片：1 天

PLACEHOLDER_IMG = "https://placehold.co/600x400/EEE/31343C?text=Travel&font=roboto"

AMAP_BASE = "https://restapi.amap.com/v3"

# 高德 POI 类型码
AMAP_TYPE_ATTRACTION = "110000"
AMAP_TYPE_FOOD = "050000"
AMAP_TYPE_HOTEL = "100000"

AMAP_TYPE_MAP = {
    "attraction": AMAP_TYPE_ATTRACTION,
    "food": AMAP_TYPE_FOOD,
    "hotel": AMAP_TYPE_HOTEL,
}

# ⭐ 多关键词策略：每类型用多组关键词覆盖细分
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
    ],
}

# 采集参数
AMAP_PAGES_PER_KEYWORD = 2      # 每个关键词翻几页
AMAP_PAGE_SIZE = 25             # 单页条数（高德上限 25）
AMAP_SLEEP = 0.4                # 高德 QPS 间隔（个人版 3次/秒）

# 数量上限（放宽版）
MAX_ATTRACTIONS = 100
MAX_FOODS = 100
MAX_HOTELS = 50

# LLM 打标批大小
TAG_BATCH_SIZE = 8
TAG_CONCURRENCY = 5


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
    cache_key = make_key("poi_v3", city, budget, companions, days,
                         intensity, tuple(sorted(prefs)))
    cached = cache_get(cache_key, POI_CACHE_TTL)
    if cached:
        logger.info("POI 缓存命中：%s", city)
        return cached

    # ── 1. 高德多关键词 × 多页采集 ─────────────────────
    logger.info("开始采集 %s 的 POI...", city)
    t0 = time.time()

    raw_attractions = _amap_search_multi(city, "attraction")
    raw_foods = _amap_search_multi(city, "food")
    raw_hotels = _amap_search_multi(city, "hotel")

    logger.info(
        "%s 高德原始：景点 %d / 美食 %d / 酒店 %d（耗时 %.1fs）",
        city, len(raw_attractions), len(raw_foods), len(raw_hotels),
        time.time() - t0,
    )

    # ── 2. 转 POICard dict ─────────────────────────────
    attractions = [_to_poi_dict(p, "attraction", city) for p in raw_attractions]
    foods = [_to_poi_dict(p, "food", city) for p in raw_foods]
    hotels_raw = [_to_poi_dict(p, "hotel", city) for p in raw_hotels]

    # ── 3. 按 (name, 坐标) 二次去重 ────────────────────
    attractions = _dedup_by_location(attractions)
    foods = _dedup_by_location(foods)
    hotels_raw = _dedup_by_location(hotels_raw)

    logger.info(
        "%s 去重后：景点 %d / 美食 %d / 酒店 %d",
        city, len(attractions), len(foods), len(hotels_raw),
    )

    # ── 4. LLM 批量打标 ────────────────────────────────
    t1 = time.time()
    attractions = _batch_enrich_tags(attractions, city)
    foods = _batch_enrich_tags(foods, city)
    logger.info("LLM 打标完成（耗时 %.1fs）", time.time() - t1)

    # ── 5. 图片补充（并发）────────────────────────────
    with ThreadPoolExecutor(max_workers=10) as pool:
        attractions = list(pool.map(_ensure_image, attractions))
        foods = list(pool.map(_ensure_image, foods))
        hotels_raw = list(pool.map(_ensure_image, hotels_raw))

    # ── 6. 偏好排序 ───────────────────────────────────
    all_pois = attractions + foods
    all_pois = score_by_preference(all_pois, prefs)
    attractions = [p for p in all_pois if p["poi_type"] == "attraction"]
    foods = [p for p in all_pois if p["poi_type"] == "food"]

    # ── 7. 酒店住宿费用计算 ───────────────────────────
    hotels_for_budget = []
    for h in hotels_raw:
        night_price = h.get("cost", 0)
        h["single_night_price"] = night_price
        h["total_accommodation_cost"] = night_price * days
        h["per_person_accommodation"] = h["total_accommodation_cost"] / max(companions, 1)
        hotels_for_budget.append(h)

    # ── 8. 预算硬过滤 ─────────────────────────────────
    all_for_budget = attractions + foods + hotels_for_budget
    filtered = filter_by_budget(all_for_budget, budget, days, companions)
    attractions = [p for p in filtered if p["poi_type"] == "attraction"]
    foods = [p for p in filtered if p["poi_type"] == "food"]
    hotels_filtered = [p for p in filtered if p["poi_type"] == "hotel"]

    # ── 9. 数量控制 ───────────────────────────────────
    attractions = attractions[:MAX_ATTRACTIONS]
    foods = foods[:MAX_FOODS]
    hotels_filtered = hotels_filtered[:MAX_HOTELS]

    logger.info(
        "%s 过滤后：景点 %d / 美食 %d / 酒店 %d（总耗时 %.1fs）",
        city, len(attractions), len(foods), len(hotels_filtered),
        time.time() - t0,
    )

    # ── 10. HotelPOI 对象 ─────────────────────────────
    hotels: list[dict] = []
    for h in hotels_filtered:
        poi = POICard(**{k: v for k, v in h.items() if k in POICard.model_fields})
        hotel_poi = HotelPOI.from_poi(poi, days, companions)
        hotels.append(hotel_poi.model_dump())

    # ── 11. POICard 列表 ──────────────────────────────
    pois: list[dict] = []
    for p in attractions + foods:
        card = POICard(**{k: v for k, v in p.items() if k in POICard.model_fields})
        pois.append(card.model_dump())

    # ── 12. 预划分行程 ────────────────────────────────
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


# ══════════════════════════════════════════════════════
# 高德采集
# ══════════════════════════════════════════════════════

def _amap_search_multi(city: str, poi_type: str) -> list[dict]:
    """多关键词 × 多页搜索，按高德 id 去重。"""
    keywords = AMAP_KEYWORDS.get(poi_type, [])
    type_code = AMAP_TYPE_MAP[poi_type]
    seen_ids: set[str] = set()
    results: list[dict] = []

    for kw in keywords:
        for page in range(1, AMAP_PAGES_PER_KEYWORD + 1):
            batch = _amap_search(city, kw, type_code, page=page)
            if not batch:
                break

            added = 0
            for p in batch:
                pid = p.get("id", "")
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)
                results.append(p)
                added += 1

            # 本页新数据不足，且返回条数小于单页上限 → 没有更多了
            if len(batch) < AMAP_PAGE_SIZE:
                break

            time.sleep(AMAP_SLEEP)

    return results


def _amap_search(
    city: str, keywords: str, type_code: str, page: int = 1,
) -> list[dict]:
    """调用高德 POI 搜索接口（支持翻页）。"""
    if not settings.amap_key:
        logger.warning("未配置高德 API Key，返回空结果")
        return []

    url = f"{AMAP_BASE}/place/text"
    params = {
        "key": settings.amap_key,
        "keywords": keywords,
        "city": city,
        "types": type_code,
        "offset": AMAP_PAGE_SIZE,
        "page": page,
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


# ══════════════════════════════════════════════════════
# POI 转换
# ══════════════════════════════════════════════════════

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
            score = score / 2
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

    # 初始 tags（LLM 打标前的兜底）
    type_name = raw.get("type", "")
    base_tags = _extract_tags(type_name)

    # ⭐ 稳定 ID（用 md5，不依赖 Python hash 随机化）
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
    """稳定的 POI ID，跨进程一致。"""
    raw = f"{city}:{poi_type}:{name}".encode("utf-8")
    h = int(hashlib.md5(raw).hexdigest()[:8], 16)
    return f"{poi_type[:3]}_{h % 10**9}"


def _dedup_by_location(pois: list[dict]) -> list[dict]:
    """按 (name, 坐标) 二次去重（防止不同关键词返回同 POI 但 id 不同）。"""
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
    """从高德类型名提取初始标签（LLM 打标前的兜底）。"""
    tags = []
    if type_name:
        parts = type_name.split(";")
        for p in parts:
            p = p.strip()
            if p and len(p) < 10:
                tags.append(p)
    return tags[:3]


def _estimate_duration(poi_type: str, cost: float) -> int:
    """估算停留时间（分钟）。"""
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
    """用 LLM 批量补充 tags 和 desc。带缓存，并发执行。"""
    if not pois:
        return []

    enriched: list[dict] = []
    to_process: list[dict] = []

    # 先查缓存
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

    # 分批并发
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
                result = fut.result()
                enriched.extend(result)
            except Exception as e:
                logger.warning("批次打标失败：%s", e)
                enriched.extend(batch)

    return enriched


def _llm_tag_batch(batch: list[dict], city: str) -> list[dict]:
    """LLM 给一批 POI 打标签。"""
    llm = get_llm(json_mode=True)

    items = [
        {
            "idx": i,
            "name": p["name"],
            "poi_type": p["poi_type"],
            "address": p.get("address", ""),
        }
        for i, p in enumerate(batch)
    ]

    prompt = f"""你是旅游 POI 打标助手。给以下 {city} 的 POI 打标签并写简介。

【输入 POI】
{json.dumps(items, ensure_ascii=False, indent=2)}

【打标规则】
1. tags: 3-5 个标签，优先从以下词库中选：
   类别：美食 / 自然 / 历史 / 购物 / 摄影 / 冒险 / 休闲 / 人文
   特色：老字号 / 网红 / 本地人推荐 / 小众 / 安静 / 适合拍照 / 亲子友好
   场所：博物馆 / 公园 / 寺庙 / 古镇 / 商圈 / 市场
   菜品：火锅 / 海鲜 / 小吃 / 早茶 / 烧烤 / 甜品 / 咖啡
   也可补充其他贴切标签。
2. desc: 20-40 字的简短介绍，突出特色。
   - 基于名称、类型、地址合理推断，不要编造具体事实（如"某名人曾到访"）
   - 信息不足时写 "{city}的一处{{类别}}" 之类的通用描述

【输出格式】
严格返回 JSON 数组，每个元素：
{{"idx": 0, "tags": ["美食", "本地人推荐"], "desc": "..."}}

只输出 JSON 数组，不要解释、不要 markdown 代码块。"""

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

        # idx → 结果 映射
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

        # 回填
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

            # 写缓存
            cache_key = make_key("tags_v1", city, p["name"], p.get("address", ""))
            cache_set(cache_key, {"tags": p["tags"], "desc": p["desc"]})

        return batch

    except Exception as e:
        logger.warning("LLM 打标失败（batch size=%d）：%s", len(batch), e)
        # 失败时保留原数据 + 空 tags
        for p in batch:
            p.setdefault("tags", [])
            p.setdefault("desc", "")
        return batch


# ══════════════════════════════════════════════════════
# 图片处理
# ══════════════════════════════════════════════════════

def _ensure_image(poi: dict) -> dict:
    """确保 POI 有图片，没有则用 Tavily 搜图 → 占位图。"""
    if poi.get("image_url"):
        return poi
    img = _tavily_image(poi.get("name", ""), poi.get("address", ""))
    poi["image_url"] = img or PLACEHOLDER_IMG
    return poi


def _tavily_image(name: str, city: str) -> str:
    """Tavily 搜图（带缓存）。"""
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