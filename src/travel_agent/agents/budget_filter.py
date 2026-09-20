"""预算硬过滤 — 超预算 POI 在进入 Agent 之前直接被代码剔除。

分项配额：
  住宿 40%  |  餐饮 35%  |  景点门票 15%  |  交通 10%
  允许整体 10% 浮动缓冲
"""
import logging

logger = logging.getLogger(__name__)

# 分项配额比例
RATIO_HOTEL = 0.40
RATIO_FOOD = 0.35
RATIO_ATTRACTION = 0.15
RATIO_TRANSPORT = 0.10
BUFFER = 1.10   # 10% 缓冲


def filter_by_budget(
    pois: list[dict],
    budget: int,
    days: int,
    companions: int,
) -> list[dict]:
    """硬性预算过滤。

    - 酒店：total_accommodation_cost > 住宿配额 → 剔除
    - 景点/美食：单笔花费 > 对应分项单日预算 → 降权但少量保留
    """
    if budget <= 0 or days <= 0:
        return pois

    hotel_budget = budget * RATIO_HOTEL * BUFFER
    food_daily = budget * RATIO_FOOD * BUFFER / days
    attr_daily = budget * RATIO_ATTRACTION * BUFFER / days

    kept: list[dict] = []
    over_budget_count = 0

    for poi in pois:
        ptype = poi.get("poi_type", "")

        if ptype == "hotel":
            # 酒店：计算全程住宿总价
            night_price = poi.get("single_night_price") or poi.get("cost", 0)
            total = night_price * days
            if total <= hotel_budget:
                kept.append(poi)
            else:
                over_budget_count += 1
                logger.debug("酒店 %s 超预算 %.0f > %.0f，剔除",
                             poi.get("name"), total, hotel_budget)

        elif ptype == "food":
            cost = poi.get("cost", 0)
            if cost <= food_daily * 1.5:
                # 单笔不超过单日预算 1.5 倍就保留
                kept.append(poi)
            else:
                over_budget_count += 1
                logger.debug("美食 %s 超预算 %.0f > %.0f，剔除",
                             poi.get("name"), cost, food_daily * 1.5)

        elif ptype == "attraction":
            cost = poi.get("cost", 0)
            if cost <= attr_daily * 1.5:
                kept.append(poi)
            else:
                over_budget_count += 1
                logger.debug("景点 %s 超预算 %.0f > %.0f，剔除",
                             poi.get("name"), cost, attr_daily * 1.5)
        else:
            kept.append(poi)

    logger.info("预算过滤：原始 %d 条，剔除 %d 条，保留 %d 条",
                len(pois), over_budget_count, len(kept))
    return kept
