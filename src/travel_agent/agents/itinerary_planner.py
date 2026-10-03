"""行程预生成 — 纯规则引擎，将 POI 分配到每天的 早/中/下午/晚 时段。

不使用 LLM，根据旅游强度规则分配：
  边走边躺：每日 2-3 点位，大量空闲
  莫名其妙地玩：每日 4-5 点位，均衡排布
  死了都要逛：每日 6-8 点位，充分利用早晚
"""
import logging

logger = logging.getLogger(__name__)

# 强度 → 每日 POI 数量范围
INTENSITY_RULES: dict[str, dict] = {
    "边走边躺":     {"min": 3, "max": 5},
    "莫名其妙地玩": {"min": 4, "max": 6},
    "死了都要逛":   {"min": 6, "max": 8},
}

# 时段分配策略：景点优先早/下午，美食优先中/晚
PERIOD_ORDER_ATTRACTION = ["morning", "afternoon", "evening", "noon"]
PERIOD_ORDER_FOOD = ["noon", "evening", "morning", "afternoon"]


def generate_initial_itinerary(
    attractions: list[dict],
    foods: list[dict],
    days: int,
    intensity: str,
) -> list[dict]:
    """根据强度规则，将景点和美食分配到每天的时段中。

    返回格式：
    [
        {
            "day": 1,
            "items": [
                {"poi_id": "att_xxx", "period": "morning"},
                {"poi_id": "food_yyy", "period": "noon"},
                ...
            ]
        },
        ...
    ]
    """
    rule = INTENSITY_RULES.get(intensity, INTENSITY_RULES["莫名其妙地玩"])
    daily_min = rule["min"]
    daily_max = rule["max"]

    # 计算每天实际分配数量
    total_pois = len(attractions) + len(foods)
    per_day = max(daily_min, min(daily_max, total_pois // max(days, 1)))

    # 初始化每天的空时段
    day_schedules: list[dict] = []
    for d in range(1, days + 1):
        day_schedules.append({"day": d, "items": []})

    # 分配景点：按 早→下午→晚→中 顺序
    att_idx = 0
    for d_idx in range(days):
        periods_used: dict[str, int] = {"morning": 0, "noon": 0, "afternoon": 0, "evening": 0}
        for period in PERIOD_ORDER_ATTRACTION:
            while att_idx < len(attractions) and periods_used[period] < 1:
                day_schedules[d_idx]["items"].append({
                    "poi_id": attractions[att_idx]["id"],
                    "period": period,
                })
                periods_used[period] += 1
                att_idx += 1
                if len(day_schedules[d_idx]["items"]) >= per_day:
                    break
            if len(day_schedules[d_idx]["items"]) >= per_day:
                break

    # 分配美食：按 中→晚→早→下午 顺序
    food_idx = 0
    for d_idx in range(days):
        current_count = len(day_schedules[d_idx]["items"])
        for period in PERIOD_ORDER_FOOD:
            while food_idx < len(foods) and current_count < per_day:
                # 检查该时段是否已有太多项
                period_count = sum(
                    1 for it in day_schedules[d_idx]["items"]
                    if it["period"] == period
                )
                if period_count >= 1:
                    break
                day_schedules[d_idx]["items"].append({
                    "poi_id": foods[food_idx]["id"],
                    "period": period,
                })
                current_count += 1
                food_idx += 1

    # 分配剩余景点
    while att_idx < len(attractions):
        # 找到 items 最少的 day
        min_day = min(day_schedules, key=lambda d: len(d["items"]))
        # 找一个合适的时段
        period = _next_period(min_day["items"])
        min_day["items"].append({
            "poi_id": attractions[att_idx]["id"],
            "period": period,
        })
        att_idx += 1

    # 分配剩余美食
    while food_idx < len(foods):
        min_day = min(day_schedules, key=lambda d: len(d["items"]))
        period = _next_period(min_day["items"], prefer_food=True)
        min_day["items"].append({
            "poi_id": foods[food_idx]["id"],
            "period": period,
        })
        food_idx += 1

    logger.info("行程预生成：%d天，强度=%s，每天%d个点位",
                days, intensity, per_day)
    return day_schedules


def _next_period(existing_items: list[dict], prefer_food: bool = False) -> str:
    """为下一个 POI 选择合适的时段。"""
    period_counts: dict[str, int] = {"morning": 0, "noon": 0, "afternoon": 0, "evening": 0}
    for item in existing_items:
        p = item.get("period", "morning")
        period_counts[p] = period_counts.get(p, 0) + 1

    if prefer_food:
        order = ["noon", "evening", "morning", "afternoon"]
    else:
        order = ["morning", "afternoon", "evening", "noon"]

    for period in order:
        if period_counts[period] < 2:
            return period
    return "afternoon"   # 兜底
