"""灵感漫游 API v2 — 城市推荐 + POI 池获取。"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import (
    ExploreCitiesRequest, ExploreCitiesResponse,
    ExplorePoisRequest, ExplorePoisResponse,
)
from ...agents.destination import recommend_cities
from ...agents.poi_collector import collect_pois_v2

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/cities", response_model=ExploreCitiesResponse)
async def explore_cities(req: ExploreCitiesRequest):
    """推荐 6 座城市，适合度由后端代码计算。"""
    try:
        candidates = await asyncio.to_thread(
            recommend_cities,
            origin=req.origin,
            budget=req.budget,
            companions=req.companions,
            days=req.days,
            intensity=req.intensity,
            preferences=req.preferences,
        )
    except Exception:
        logger.exception("explore_cities failed")
        raise HTTPException(500, "推荐城市失败")

    return ExploreCitiesResponse(candidates=candidates)


@router.post("/pois", response_model=ExplorePoisResponse)
async def explore_pois(req: ExplorePoisRequest):
    """获取城市 POI 池 + AI 预生成初始行程。

    流程：高德搜索 → 图片补充 → 偏好排序 → 预算过滤 → 行程预生成
    """
    try:
        result = await asyncio.to_thread(
            collect_pois_v2,
            city=req.city,
            budget=req.budget,
            companions=req.companions,
            days=req.days,
            intensity=req.intensity,
            preferences=req.preferences,
        )
    except Exception:
        logger.exception("explore_pois failed")
        raise HTTPException(500, "获取 POI 失败")

    return ExplorePoisResponse(
        city=req.city,
        pois=result.get("pois", []),
        hotels=result.get("hotels", []),
        initial_itinerary=result.get("initial_itinerary", []),
    )


class ReplanRequest(BaseModel):
    """重新规划行程请求。"""
    city: str
    hotel_id: str
    pois: list[dict]
    hotels: list[dict]
    days: int


@router.post("/replan")
async def replan_itinerary(req: ReplanRequest):
    """根据选中的酒店重新规划行程。

    以酒店位置为锚点，重新分配景点到各时段。
    """
    from ...agents.itinerary_planner import generate_initial_itinerary

    try:
        # 找到选中的酒店
        hotel = next((h for h in req.hotels if h["id"] == req.hotel_id), None)
        if not hotel:
            raise HTTPException(404, "酒店不存在")

        # 分离景点和餐食
        attractions = [p for p in req.pois if p.get("poi_type") == "attraction"]
        foods = [p for p in req.pois if p.get("poi_type") == "food"]

        # 重新生成行程（传入酒店位置作为参考）
        new_itinerary = generate_initial_itinerary(
            attractions=attractions,
            foods=foods,
            days=req.days,
            intensity="莫名其妙地玩",  # 默认强度
            hotel_lat=hotel.get("lat"),
            hotel_lng=hotel.get("lng"),
        )

        return {
            "itinerary": new_itinerary,
            "hotel": hotel,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("replan failed")
        raise HTTPException(500, "重新规划失败")
