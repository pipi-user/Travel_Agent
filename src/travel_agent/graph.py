"""LangGraph 编排：拿到 POI 池。"""
from langgraph.graph import StateGraph, START, END

from .state import TravelState
from .schemas import TripRequest
from .agents.destination import recommend_destinations
from .agents.poi_collector import collect_pois
from .memory.store import load_profile
from .config import settings


def load_memory(state: TravelState) -> dict:
    uid = state.get("user_id") or settings.user_id
    print(f"[DEBUG] load_memory: user_id={uid}")
    return {"user_profile": load_profile(uid)}


def parse_request(state: TravelState) -> dict:
    print(f"[DEBUG] parse_request: state keys={list(state.keys())}")
    req = TripRequest(**state["request"])
    selected = state.get("selected_city") or req.dest_city or None
    return {"request": req.model_dump(), "selected_city": selected}


def route_after_parse(state: TravelState) -> str:
    return "collect" if state.get("selected_city") else "recommend"


def collect_pois_node(state: TravelState) -> dict:
    req = state["request"]
    pool = collect_pois(
        city=state["selected_city"],
        preferences=req.get("preferences", []),
        days=req.get("days", 3),
        companions=req.get("companions", "独自"),
        user_id=state.get("user_id", ""),   # ⭐ 传递
    )
    return {
        "attractions": pool["attractions"],
        "food": pool["foods"],
        "accommodation": pool["hotels"],
    }


def build_explore_graph(checkpointer=None):
    builder = StateGraph(TravelState)
    builder.add_node("load_memory", load_memory)
    builder.add_node("parse", parse_request)
    builder.add_node("recommend", recommend_destinations)
    builder.add_node("collect", collect_pois_node)

    builder.add_edge(START, "load_memory")
    builder.add_edge("load_memory", "parse")
    builder.add_conditional_edges(
        "parse", route_after_parse,
        {"recommend": "recommend", "collect": "collect"},
    )
    builder.add_edge("recommend", END)
    builder.add_edge("collect", END)
    return builder.compile(checkpointer=checkpointer)


build_recommend_graph = build_explore_graph