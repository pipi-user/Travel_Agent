"""严格预算核算 — 纯 Python 数值计算，不调用 LLM。

总花费 = 城际往返 + 住宿 + 餐饮 + 景点 + 市内交通
"""
import logging
from math import ceil

from .intercity import get_roundtrip_cost

logger = logging.getLogger(__name__)

# 分项默认单价（元）
FOOD_PER_DAY_PER_PERSON = 100     # 餐饮：人均日消费
LOCAL_TRANSPORT_PER_DAY = 50      # 市内交通：人均日消费
DEFAULT_HOTEL_PRICE = 300         # 酒店单晚参考价（无选中酒店时）


def calculate_full_budget(
    origin: str,
    city: str,
    days: int,
    companions: int,
    budget: int,
    hotel: dict | None = None,
    attractions: list[dict] | None = None,
) -> dict:
    """严格核算行程总花费。纯 Python，不依赖 LLM。"""
    companions = max(1, companions)
    days = max(1, days)

    # 1. 城际往返
    intercity = get_roundtrip_cost(origin, city, companions)
    if intercity < 0:
        intercity = 0.0    # 查不到按 0 处理，不影响其他项

    # 2. 住宿：双人间，房间数 = ceil(人数/2)，晚数 = 天数-1
    night_price = (hotel or {}).get("single_night_price") or DEFAULT_HOTEL_PRICE
    rooms = max(1, ceil(companions / 2))
    hotel_cost = night_price * max(days - 1, 0) * rooms

    # 3. 餐饮
    food_cost = FOOD_PER_DAY_PER_PERSON * days * companions

    # 4. 景点门票
    ticket_cost = sum(float(p.get("cost", 0) or 0) for p in (attractions or [])) * companions

    # 5. 市内交通
    local_cost = LOCAL_TRANSPORT_PER_DAY * days * companions

    total = intercity + hotel_cost + food_cost + ticket_cost + local_cost

    return {
        "intercity": round(intercity, 1),
        "hotel": round(hotel_cost, 1),
        "food": round(food_cost, 1),
        "ticket": round(ticket_cost, 1),
        "local": round(local_cost, 1),
        "total": round(total, 1),
        "budget": budget,
        "remaining": round(budget - total, 1),
        "over_budget": total > budget,
    }


def estimate_minimum_daily_budget(
    origin: str,
    city: str,
    days: int,
    companions: int,
    budget: int,
) -> float:
    """返回"扣除城际费后，团队每日可支配预算（元）"。

    - 返回 > 0：可支配日均（团队总额）
    - 返回 -1：城际费查询失败（调用方需谨慎处理）
    - 返回 -2：城际费都付不起（严重超预算，应直接淘汰）
    """
    intercity = get_roundtrip_cost(origin, city, companions)

    # 查询失败 → 不淘汰，返回 -1 让调用方知道
    if intercity < 0:
        return -1.0

    remaining = budget - intercity

    # ⭐ 城际费都付不起 → 返回 -2，调用方直接淘汰
    if remaining <= 0:
        return -2.0

    return remaining / max(days, 1)