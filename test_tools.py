from src.travel_agent.tools.amap import search_poi, get_weather

print("=== 测试高德POI搜索 ===")
print(search_poi.invoke({"keywords": "洱海", "city": "大理"}))

print("\n=== 测试高德天气 ===")
print(get_weather.invoke("大理"))