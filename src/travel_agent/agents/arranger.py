"""行程编排：唯一的「POI 顺序 → 时间轴行程」出口。

被两个地方调用：
  - /api/plan/arrange   （探索模式：用户拖拽后的排序）
  - /api/target/plan    （目标模式：LLM 默认排序，用户可再拖）

只做 3 件事：
  1. 规则引擎分配时间（不花 LLM 钱）
  2. 生成地图数据
  3. LLM 写一句每日总结（可选）
"""
from datetime import datetime, timedelta

from ..llm import get_llm
from ..schemas import ItineraryDay, ItineraryItem, ItineraryResult

# 不同节奏对应的站点间隔（分钟，含交通时间）
STEP_BASE = {"轻松": 40, "适中": 30, "紧凑": 20}

START_TIME = "09:00"
LUNCH_AT = 11          # 11 点后遇到景点前插午餐
DINNER_HOUR = 18


def arrange_itinerary(
    request: dict,
    city: str,
    days_slots: list[dict],      # [{"day": 1, "items": ["attr_xxx", "food_yyy"]}]
    poi_pool: list[dict],         # 完整 POICard 列表
    hotel: dict | None = None,
    pace: str = "适中",
) -> dict:
    """主入口。"""
    poi_map = {p["id"]: p for p in poi_pool}
    step = STEP_BASE.get(pace, 30)

    structured_days: list[ItineraryDay] = []
    unscheduled: list[str] = []

    for slot in days_slots:
        ids = slot.get("items", [])
        day_pois = []
        for pid in ids:
            if pid in poi_map:
                day_pois.append(poi_map[pid])
            else:
                unscheduled.append(pid)

        day = _build_day(
            day_num=slot["day"],
            city=city,
            pois=day_pois,
            step=step,
            hotel=hotel,
        )
        structured_days.append(day)

    # 全局汇总
    points = [
        {"lat": p["lat"], "lng": p["lng"], "name": p["name"]}
        for p in poi_pool
        if p.get("lat") and p.get("lng")
    ]

    result = ItineraryResult(
        days=structured_days,
        total_cost=sum(d.daily_cost for d in structured_days),
        summary=_llm_summary(request, structured_days, city),
        map_center=_center(points),
        unscheduled=unscheduled,
    )
    return result.model_dump()


# ---------- 单日构建 ----------

def _build_day(
    day_num: int, city: str, pois: list[dict],
    step: int, hotel: dict | None,
) -> ItineraryDay:
    current = datetime.strptime(START_TIME, "%H:%M")
    items: list[ItineraryItem] = []
    has_lunch = has_dinner = False

    for poi in pois:
        ptype = poi.get("poi_type", "attraction")

        # 午餐插入
        if not has_lunch and current.hour >= LUNCH_AT and ptype == "attraction":
            items.append(_meal("午餐", current, 60, 50))
            current += timedelta(minutes=60)
            has_lunch = True

        # 晚餐插入
        if not has_dinner and current.hour >= DINNER_HOUR and ptype != "food":
            items.append(_meal("晚餐", current, 60, 80))
            current += timedelta(minutes=60)
            has_dinner = True

        duration = int(poi.get("duration", 90) or 90)
        items.append(ItineraryItem(
            time=current.strftime("%H:%M"),
            type=ptype,
            poi_id=poi["id"],
            activity=poi["name"],
            location=poi.get("address", ""),
            cost=float(poi.get("cost", 0) or 0),
            duration_min=duration,
            note=poi.get("desc", ""),
        ))
        current += timedelta(minutes=duration + step)

    # 兜底：晚餐
    if not has_dinner and pois:
        items.append(_meal("晚餐", current, 60, 80))

    # 回酒店
    if hotel:
        items.append(ItineraryItem(
            time=(current + timedelta(minutes=30)).strftime("%H:%M"),
            type="hotel",
            poi_id=hotel.get("id", ""),
            activity=f"返回 {hotel.get('name', '酒店')}",
            location=hotel.get("address", ""),
        ))

    day = ItineraryDay(
        day=day_num,
        city=city,
        hotel=hotel.get("name", "") if hotel else "",
        intensity=_intensity(len(pois)),
        items=items,
        transport_note=_route_hint(pois),
        daily_cost=_sum_cost(items),
        map_points=[
            {"lat": p["lat"], "lng": p["lng"], "name": p["name"]}
            for p in pois if p.get("lat") and p.get("lng")
        ],
    )
    return day


def _meal(label: str, when: datetime, dur: int, cost: float) -> ItineraryItem:
    return ItineraryItem(
        time=when.strftime("%H:%M"),
        type="food",
        activity=label,
        cost=cost,
        duration_min=dur,
    )


def _intensity(n: int) -> str:
    if n <= 3:
        return "轻松"
    if n <= 6:
        return "适中"
    return "紧凑"


def _sum_cost(items: list[ItineraryItem]) -> float:
    """所有 item 的 cost 求和（现在 cost 已是数值）。"""
    return sum(float(it.cost or 0) for it in items)


def _route_hint(pois: list[dict]) -> str:
    names = [p["name"] for p in pois if p.get("poi_type") == "attraction"]
    if len(names) < 2:
        return ""
    return " → ".join(names)


def _center(points: list[dict]) -> dict:
    if not points:
        return {}
    return {
        "lat": sum(p["lat"] for p in points) / len(points),
        "lng": sum(p["lng"] for p in points) / len(points),
    }


# ---------- LLM 只写总结（可选，失败不影响主流程）----------

def _llm_summary(request: dict, days: list[ItineraryDay], city: str) -> str:
    try:
        llm = get_llm()
        outline = "\n".join(
            f"Day{d.day}: " + "、".join(i.activity for i in d.items if i.activity)[:80]
            for d in days
        )
        resp = llm.invoke(
            f"用一句不超过 40 字的话总结这次 {city} 之行：\n{outline}"
        )
        return (resp.content if hasattr(resp, "content") else str(resp)).strip()
    except Exception:
        return f"{city} {len(days)} 日行程"