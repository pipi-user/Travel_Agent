"""目标模式 API：一句话 → POI 池 + 默认排序 + 默认行程。"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException

from ..models import TargetPlanRequest, TargetPlanResponse
from ...agents.poi_collector import collect_pois
from ...agents.arranger import arrange_itinerary

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/plan", response_model=TargetPlanResponse)
async def target_plan(req: TargetPlanRequest):
    try:
        pool = await asyncio.to_thread(
            collect_pois, req.dest_city, [], req.days, req.companions,req.user_id, 
        )
        default_slots = _auto_schedule(pool, req.days)
        itinerary = await asyncio.to_thread(
            arrange_itinerary,
            req.model_dump(),
            req.dest_city,
            [s.model_dump() for s in default_slots],
            pool["attractions"] + pool["foods"],
            pool["hotels"][0] if pool["hotels"] else None,
            req.pace,
        )
    except Exception:
        logger.exception("target_plan failed")
        raise HTTPException(500, "生成行程失败")

    return TargetPlanResponse(
        city=req.dest_city,
        attractions=pool["attractions"],
        foods=pool["foods"],
        hotels=pool["hotels"],
        default_slots=default_slots,
        itinerary=itinerary,
    )


def _auto_schedule(pool: dict, days: int) -> list:
    """根据天数自动分配 POI 到每天"""
    from ...schemas import DaySlot
    attractions = [a["id"] for a in pool["attractions"]]
    foods = [f["id"] for f in pool["foods"]]

    slots = []
    a_idx = f_idx = 0
    
    # 每天分配 2 个景点 + 1-2 个美食
    for d in range(1, days + 1):
        items = []
        # 每天 2 个景点
        for _ in range(2):
            if a_idx < len(attractions):
                items.append(attractions[a_idx])
                a_idx += 1
        # 每天 1-2 个美食（根据剩余美食数量）
        remaining_foods = len(foods) - f_idx
        remaining_days = days - d + 1
        foods_per_day = max(1, remaining_foods // remaining_days) if remaining_days > 0 else 1
        for _ in range(min(foods_per_day, 2)):
            if f_idx < len(foods):
                items.append(foods[f_idx])
                f_idx += 1
        slots.append(DaySlot(day=d, items=items))
    
    # 分配剩余的 POI
    while a_idx < len(attractions) or f_idx < len(foods):
        # 找到 items 最少的 day
        min_slot = min(slots, key=lambda s: len(s.items))
        if a_idx < len(attractions):
            min_slot.items.append(attractions[a_idx])
            a_idx += 1
        elif f_idx < len(foods):
            min_slot.items.append(foods[f_idx])
            f_idx += 1
    
    return slots