from src.travel_agent.agents.intent_parser import parse_intent
from src.travel_agent.agents.smart_planner import generate_smart_itinerary
import json

text = "我在2026年中秋节三天想和一个朋友从中山石岐出发去汕头旅游，计划25号下午乘坐高铁到达最近的汕头站，然后晚上去看一个电影，吃一个宵夜，等第二天再开始正式参观，第三天下午就要返回，帮我规划路线和进行推荐"

print("=" * 60)
print("【第1步】意图解析")
intent = parse_intent(text)
print(json.dumps(intent.model_dump(), ensure_ascii=False, indent=2))

print("\n" + "=" * 60)
print("【第2步】智能规划")
result = generate_smart_itinerary(intent.model_dump())
print(json.dumps(result, ensure_ascii=False, indent=2))