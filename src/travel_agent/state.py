from typing import Optional, TypedDict


class TravelState(TypedDict, total=False):
    request: dict
    user_id: str
    user_profile: dict
    candidates: list[dict]
    selected_city: Optional[str]
    attractions: list[dict]
    food: list[dict]
    accommodation: list[dict]
    itinerary: Optional[dict]