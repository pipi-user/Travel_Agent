"""路线规划 API v2 — 接收用户编辑完成的行程，批量调用高德路线 API。"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException

import httpx

from ..models import RouteRequest
from ...schemas import RouteResponse, RouteDay, TransportSegment
from ...config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

AMAP_BASE = "https://restapi.amap.com/v3"


@router.post("/route", response_model=RouteResponse)
async def plan_route(req: RouteRequest):
    """接收用户编辑完成的行程，批量计算交通路线。

    按天遍历 slots，逐段调用高德方向 API。
    """
    # 构建 POI id → info 映射
    poi_map: dict[str, dict] = {}
    for p in req.pois:
        poi_map[p.get("id", "")] = p

    route_days: list[RouteDay] = []
    total_cost = 0.0

    for day_schedule in req.slots:
        day_num = day_schedule.day
        # 提取当天有序 POI 列表（保留 period 字段）
        day_items = []
        for slot_item in day_schedule.items:
            poi_info = poi_map.get(slot_item.poi_id, {})
            if poi_info:
                # 合并 POI 数据和时段信息
                item = {**poi_info, "period": slot_item.period}
                day_items.append(item)

        if not day_items:
            route_days.append(RouteDay(day=day_num))
            continue

        # 逐段计算交通
        segments: list[TransportSegment] = []
        daily_cost = 0.0

        for i in range(len(day_items) - 1):
            from_poi = day_items[i]
            to_poi = day_items[i + 1]

            seg = await _calc_transport(from_poi, to_poi)
            segments.append(seg)
            daily_cost += seg.cost

        # 加上各 POI 自身花费
        for poi in day_items:
            daily_cost += poi.get("cost", 0)

        total_cost += daily_cost

        route_days.append(RouteDay(
            day=day_num,
            items=day_items,
            segments=segments,
            daily_cost=daily_cost,
        ))

    # 酒店信息 + 住宿费用
    hotel_info = req.hotel if req.hotel else None
    if hotel_info:
        hotel_cost = hotel_info.get("total_accommodation_cost", 0) or hotel_info.get("single_night_price", 0) * req.days
        total_cost += hotel_cost

    return RouteResponse(
        city=req.city,
        days=route_days,
        hotel_info=hotel_info,
        total_cost=total_cost,
    )


async def _calc_transport(from_poi: dict, to_poi: dict) -> TransportSegment:
    """调用高德方向 API 计算两点间交通。"""
    from_lng = from_poi.get("lng", 0)
    from_lat = from_poi.get("lat", 0)
    to_lng = to_poi.get("lng", 0)
    to_lat = to_poi.get("lat", 0)

    from_name = from_poi.get("name", "")
    to_name = to_poi.get("name", "")

    if not settings.amap_key or not from_lng or not to_lng:
        return TransportSegment(
            from_name=from_name,
            to_name=to_name,
            from_lng=from_lng,
            from_lat=from_lat,
            to_lng=to_lng,
            to_lat=to_lat,
            mode="driving",
            distance_km=5.0,
            duration_min=15,
            cost=0,
        )

    origin = f"{from_lng},{from_lat}"
    destination = f"{to_lng},{to_lat}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{AMAP_BASE}/direction/driving",
                params={
                    "key": settings.amap_key,
                    "origin": origin,
                    "destination": destination,
                },
            )
            data = resp.json()
            if data.get("status") != "1":
                raise ValueError(data.get("info", "API error"))

            paths = data.get("route", {}).get("paths", [])
            if not paths:
                raise ValueError("no paths found")

            path = paths[0]
            distance = int(path.get("distance", 0))
            duration = int(path.get("duration", 0))

            return TransportSegment(
                from_name=from_name,
                to_name=to_name,
                from_lng=from_lng,
                from_lat=from_lat,
                to_lng=to_lng,
                to_lat=to_lat,
                mode="driving",
                distance_km=round(distance / 1000, 1),
                duration_min=round(duration / 60),
                cost=0,  # 驾车不计算费用
            )
    except Exception as e:
        logger.warning("高德路线计算失败 %s → %s: %s", from_name, to_name, e)
        return TransportSegment(
            from_name=from_name,
            to_name=to_name,
            from_lng=from_lng,
            from_lat=from_lat,
            to_lng=to_lng,
            to_lat=to_lat,
            mode="driving",
            distance_km=5.0,
            duration_min=15,
            cost=0,
        )
