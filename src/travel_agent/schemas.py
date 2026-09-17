#定义 Agent 输出的数据长什么样
from pydantic import BaseModel, Field

class TravelRequest(BaseModel):
    origin: str
    budget: int
    days: int
    month: int
    preferences: list[str] = []
    pace: str = "适中"
    companions: str = "独自"

class Destination(BaseModel):
    city: str
    reason: str
    score: float = Field(ge=0, le=10)
    estimated_cost: int
    weather: str

class DestinationList(BaseModel):
    destinations: list[Destination]