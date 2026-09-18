import httpx
from langchain_core.tools import tool
from ..config import settings

AMAP_BASE = "https://restapi.amap.com/v3"

@tool
def search_poi(keywords: str, city: str) -> str:
    """高德地图搜索景点、餐厅、酒店等POI。输入关键词和城市名。"""
    if not settings.amap_key:
        return "未配置高德地图API Key。"
    
    url = f"{AMAP_BASE}/place/text"
    params = {
        "key": settings.amap_key,
        "keywords": keywords,
        "city": city,
        "offset": 5,
        "page": 1,
        "extensions": "all",
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params=params)
            data = resp.json()
            if data.get("status") != "1":
                return f"高德API报错：{data.get('info')}"
            
            pois = data.get("pois", [])
            if not pois:
                return f"在{city}没有找到关于「{keywords}」的结果。"
            
            lines = []
            for p in pois[:5]:
                name = p.get("name", "")
                address = p.get("address", "")
                if isinstance(address, list): address = "".join(address)
                if not address: address = "暂无地址"
                
                rating = p.get("biz_ext", {}).get("rating", "暂无评分")
                if not rating or rating == []: rating = "暂无评分"
                
                cost = p.get("biz_ext", {}).get("cost", "暂无")
                # 修复空列表问题
                if isinstance(cost, list): cost = "暂无"
                if not cost: cost = "暂无"
                
                lines.append(f"📍 {name} | 地址：{address} | 评分：{rating} | 人均：{cost}")
            return "\n".join(lines)
    except Exception as e:
        return f"请求高德地图失败：{e}"

@tool
def get_weather(city: str) -> str:
    """高德地图查询城市天气。输入城市名（如：大理）。"""
    if not settings.amap_key:
        return "未配置高德地图API Key。"
    
    # 高德天气API需要城市的adcode，先通过地理编码查询
    geo_url = f"{AMAP_BASE}/geocode/geo"
    try:
        with httpx.Client(timeout=10) as client:
            # 1. 获取城市adcode
            geo_resp = client.get(geo_url, params={"key": settings.amap_key, "address": city})
            geo_data = geo_resp.json()
            if geo_data.get("status") != "1" or not geo_data.get("geocodes"):
                return f"无法找到城市：{city}"
            adcode = geo_data["geocodes"][0]["adcode"]
            
            # 2. 查询天气
            weather_url = f"{AMAP_BASE}/weather/weatherInfo"
            w_resp = client.get(weather_url, params={"key": settings.amap_key, "city": adcode, "extensions": "all"})
            w_data = w_resp.json()
            if w_data.get("status") != "1":
                return f"天气查询失败：{w_data.get('info')}"
            
            forecasts = w_data.get("forecasts", [])
            if not forecasts:
                return f"暂时没有{city}的天气预报。"
            
            casts = forecasts[0].get("casts", [])
            lines = [f"🌤 {city}未来天气："]
            for c in casts[:3]:  # 只取前3天
                lines.append(f"{c['date']}：白天{c['dayweather']}，夜间{c['nightweather']}，气温{c['nighttemp']}~{c['daytemp']}℃")
            return "\n".join(lines)
    except Exception as e:
        return f"请求高德天气失败：{e}"