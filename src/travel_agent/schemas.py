"""领域数据模型 — 灵感漫游 v2。"""
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ============ POI 卡片 ============

class POICard(BaseModel):
    """景点 / 美食 / 酒店 统一卡片模型。"""
    id: str
    name: str
    poi_type: Literal["attraction", "food", "hotel"]
    score: float = 0.0              # 评分 0-5
    desc: str = ""                   # 简短介绍
    cost: float = 0.0               # 预估单笔花费（元，数值）
    duration: int = 90               # 预估耗时（分钟）
    lat: float = 0.0
    lng: float = 0.0
    image_url: str = ""
    tags: list[str] = Field(default_factory=list)
    address: str = ""

    @field_validator("cost", mode="before")
    @classmethod
    def _parse_cost(cls, v):
        if isinstance(v, str):
            import re
            nums = re.findall(r"[\d.]+", v.replace(",", ""))
            return float(nums[0]) if nums else 0.0
        return float(v) if v else 0.0

    @field_validator("score", mode="before")
    @classmethod
    def _parse_score(cls, v):
        if isinstance(v, str):
            import re
            nums = re.findall(r"[\d.]+", v)
            return float(nums[0]) if nums else 0.0
        return float(v) if v else 0.0


class HotelPOI(POICard):
    """酒店卡片，额外携带住宿费用计算字段。"""
    poi_type: Literal["hotel"] = "hotel"
    single_night_price: float = 0.0
    total_accommodation_cost: float = 0.0   # = single_night_price * days
    per_person_accommodation: float = 0.0   # = total / companions

    @classmethod
    def from_poi(cls, poi: POICard, days: int, companions: int) -> "HotelPOI":
        night_price = poi.cost if poi.cost > 0 else 0.0
        total = night_price * days
        per_person = total / max(companions, 1)
        return cls(
            **poi.model_dump(),
            single_night_price=night_price,
            total_accommodation_cost=total,
            per_person_accommodation=per_person,
        )


# ============ 时间槽 & 日程 ============

class TimeSlotItem(BaseModel):
    """时间槽中的单个 POI 条目。"""
    poi_id: str
    period: Literal["morning", "noon", "afternoon", "evening"] = "morning"


class DaySchedule(BaseModel):
    """一天的行程安排。"""
    day: int
    items: list[TimeSlotItem] = Field(default_factory=list)


# ============ 路线规划 ============

class TransportSegment(BaseModel):
    """两点之间的交通段。"""
    from_name: str
    to_name: str
    from_lng: float = 0.0
    from_lat: float = 0.0
    to_lng: float = 0.0
    to_lat: float = 0.0
    mode: str = "driving"
    distance_km: float = 0.0
    duration_min: int = 0
    cost: float = 0.0


class RouteDay(BaseModel):
    """单日路线详情。"""
    day: int
    items: list[dict] = Field(default_factory=list)       # 有序 POI 列表
    segments: list[TransportSegment] = Field(default_factory=list)
    daily_cost: float = 0.0


class RouteResponse(BaseModel):
    """最终路线响应。"""
    city: str
    days: list[RouteDay] = Field(default_factory=list)
    hotel_info: Optional[dict] = None
    total_cost: float = 0.0
