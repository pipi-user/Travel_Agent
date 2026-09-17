from typing import TypedDict, Optional

class TravelState(TypedDict):
    request: dict
    candidates: list[dict]
    selected_city: Optional[str]
    itinerary: Optional[dict]