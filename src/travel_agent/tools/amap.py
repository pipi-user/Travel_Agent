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
        "offset": 10,
        "page": 1,
        "extensions": "all",   # 必须为all才会返回图片
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
            for p in pois[:10]:
                name = p.get("name", "")
                address = p.get("address", "")
                if isinstance(address, list):
                    address = "".join(address)
                if not address:
                    address = "暂无地址"

                # 坐标（重要！地图和跳转都用它）
                location = p.get("location", "")
                lng, lat = ("", "")
                if location and "," in location:
                    lng, lat = location.split(",")

                rating = p.get("biz_ext", {}).get("rating", "暂无评分")
                if not rating or rating == []:
                    rating = "暂无评分"
                cost = p.get("biz_ext", {}).get("cost", "暂无")
                if isinstance(cost, list):
                    cost = "暂无"
                if not cost:
                    cost = "暂无"

                # 提取图片
                photos = p.get("photos", [])
                photo_url = photos[0].get("url", "") if photos else ""

                line = (
                    f"📍 {name} | 地址：{address} | 评分：{rating} | "
                    f"人均：{cost} | 坐标：{lng},{lat} | 图片：{photo_url}"
                )
                lines.append(line)
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

@tool
def plan_route(origin: str, destination: str, mode: str = "driving") -> str:
    """高德路径规划。mode可选：driving(驾车)、walking(步行)、transit(公交)、riding(骑行)。"""
    if not settings.amap_key:
        return "未配置高德地图API Key。"
    
    url = f"{AMAP_BASE}/direction/{mode}"
    params = {
        "key": settings.amap_key,
        "origin": origin,       # 需要是"经度,纬度"格式，或先做地理编码
        "destination": destination,
    }
    # 注意：高德路径API需要经纬度坐标，这里先简化处理，Day4正式做地理编码
    # 在实际使用时，先调用 geocode 把城市名转成坐标
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params=params)
            data = resp.json()
            if data.get("status") != "1":
                return f"路径规划失败：{data.get('info')}"
            route = data.get("route", {})
            paths = route.get("paths", [])
            if not paths:
                return "未找到可行路线。"
            p = paths[0]
            distance = p.get("distance", "未知")
            duration = p.get("duration", "未知")
            return f"从{origin}到{destination}：距离{int(distance)/1000:.1f}公里，预计耗时{int(duration)/60:.0f}分钟。"
    except Exception as e:
        return f"路径规划请求失败：{e}"


@tool
def search_hotel(city: str, keywords: str = "酒店") -> str:
    """高德搜索酒店或民宿。输入城市名和关键词。"""
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
        "types": "100000",  # 高德POI类型：住宿服务
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params=params)
            data = resp.json()
            if data.get("status") != "1":
                return f"高德API报错：{data.get('info')}"
            pois = data.get("pois", [])
            if not pois:
                return f"在{city}没有找到住宿结果。"
            lines = []
            for p in pois[:5]:
                name = p.get("name", "")
                address = p.get("address", "")
                if isinstance(address, list): address = "".join(address)
                rating = p.get("biz_ext", {}).get("rating", "暂无评分")
                cost = p.get("biz_ext", {}).get("cost", "暂无")
                if isinstance(cost, list): cost = "暂无"
                lines.append(f"🏨 {name} | 地址：{address} | 评分：{rating} | 参考价：{cost}")
            return "\n".join(lines)
    except Exception as e:
        return f"请求高德酒店失败：{e}"