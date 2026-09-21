"""API 请求 / 响应模型 — 灵感漫游 v2。"""
from typing import Optional
from pydantic import BaseModel, Field

from ..schemas import POICard, HotelPOI, DaySchedule, RouteResponse


# ---------- 城市推荐 ----------

class ExploreCitiesRequest(BaseModel):
    origin: str                        # 出发地
    budget: int = 5000                 # 总预算（元）
    companions: int = 1                # 出行人数
    days: int = 3                      # 出行天数
    intensity: str = "莫名其妙地玩"     # 旅游强度
    preferences: list[str] = Field(default_factory=list)
    age: Optional[int] = None


class CityCandidate(BaseModel):
    city: str
    score: float = 0.0                 # 后端代码计算的适合度
    reason: str = ""                   # 一句话推荐
    image_url: str = ""
    intro: str = ""                    # LLM 生成的简短介绍
    tags: list[str] = []          # ⭐ 新增
    daily_cost: int = 0     

class ExploreCitiesResponse(BaseModel):
    candidates: list[CityCandidate] = Field(default_factory=list)


# ---------- POI 池 ----------

class ExplorePoisRequest(BaseModel):
    city: str
    budget: int = 5000
    companions: int = 1
    days: int = 3
    intensity: str = "莫名其妙地玩"
    preferences: list[str] = Field(default_factory=list)


class ExplorePoisResponse(BaseModel):
    city: str
    pois: list[POICard] = Field(default_factory=list)
    hotels: list[HotelPOI] = Field(default_factory=list)
    initial_itinerary: list[DaySchedule] = Field(default_factory=list)


# ---------- 路线规划 ----------

class RouteRequest(BaseModel):
    city: str
    days: int
    slots: list[DaySchedule] = Field(default_factory=list)
    hotel: Optional[dict] = None       # 选中的酒店信息
    pois: list[dict] = Field(default_factory=list)  # 前端回传完整 POI 池


# ---------- 保留兼容旧记忆模块 ----------

class TargetPlanRequest(BaseModel):
    user_id: str = "demo"
    origin: str = ""
    dest_city: str = ""
    start_date: str = ""
    days: int = 3
    pace: str = "适中"
    companions: str = "独自"
    extra_notes: str = ""
