"""灵感漫游 API v2 — 城市推荐 + POI 池获取。"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException

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
