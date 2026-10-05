"""城市元数据 + 距离计算。

优先级：
  1. data/city_meta.json（LLM 生成的 372 城市画像）
  2. CORE_CITIES（30 个核心城市硬编码）
  3. 默认值
"""
import json
import math
from functools import lru_cache
from pathlib import Path

CITIES_FILE = Path("data/cities.json")
CITY_META_FILE = Path("data/city_meta.json")

DEFAULT_TAGS = ["城市", "人文"]
DEFAULT_DAILY_COST = 400
DEFAULT_BASE_SCORE = 6.5


CORE_CITIES: dict[str, dict] = {
    "北京": {"tags": ["历史", "文化", "古迹", "博物馆", "皇家", "胡同"], "daily_cost": 600, "base_score": 9.3},
    "上海": {"tags": ["现代", "购物", "美食", "都市", "夜景", "艺术"], "daily_cost": 700, "base_score": 9.1},
    "广州": {"tags": ["美食", "本地菜", "小吃", "岭南", "花市", "休闲"], "daily_cost": 450, "base_score": 8.6},
    "深圳": {"tags": ["现代", "购物", "科技", "主题公园", "海滨"], "daily_cost": 600, "base_score": 8.3},
    "成都": {"tags": ["美食", "休闲", "熊猫", "茶馆", "慢生活", "火锅"], "daily_cost": 400, "base_score": 9.2},
    "杭州": {"tags": ["自然", "山水", "湖", "茶园", "历史", "丝绸"], "daily_cost": 550, "base_score": 9.0},
    "西安": {"tags": ["历史", "古迹", "美食", "文化", "兵马俑", "回民街"], "daily_cost": 400, "base_score": 8.9},
    "重庆": {"tags": ["美食", "火锅", "夜景", "山城", "历史", "网红"], "daily_cost": 400, "base_score": 8.8},
    "厦门": {"tags": ["海滨", "文艺", "休闲", "摄影", "鼓浪屿", "海鲜"], "daily_cost": 500, "base_score": 8.6},
    "大理": {"tags": ["自然", "休闲", "摄影", "古城", "洱海", "民族"], "daily_cost": 350, "base_score": 8.5},
    "丽江": {"tags": ["古城", "自然", "摄影", "雪山", "民族", "休闲"], "daily_cost": 400, "base_score": 8.6},
    "三亚": {"tags": ["海滨", "度假", "海鲜", "休闲", "热带", "沙滩"], "daily_cost": 600, "base_score": 8.7},
    "桂林": {"tags": ["自然", "山水", "摄影", "梯田", "漓江", "户外"], "daily_cost": 350, "base_score": 8.4},
    "长沙": {"tags": ["美食", "小吃", "网红", "历史", "娱乐", "夜生活"], "daily_cost": 350, "base_score": 8.6},
    "武汉": {"tags": ["美食", "历史", "樱花", "湖", "文化", "热干面"], "daily_cost": 350, "base_score": 8.2},
    "南京": {"tags": ["历史", "文化", "美食", "古迹", "民国", "梧桐"], "daily_cost": 450, "base_score": 8.6},
    "青岛": {"tags": ["海滨", "啤酒", "海鲜", "欧式", "休闲", "摄影"], "daily_cost": 450, "base_score": 8.5},
    "苏州": {"tags": ["园林", "历史", "水乡", "丝绸", "精致", "古镇"], "daily_cost": 500, "base_score": 8.6},
    "昆明": {"tags": ["自然", "花海", "春城", "民族", "休闲", "石林"], "daily_cost": 350, "base_score": 8.3},
    "哈尔滨": {"tags": ["冰雪", "俄式", "美食", "冬季", "建筑", "冰雕"], "daily_cost": 400, "base_score": 8.2},
    "郑州": {"tags": ["历史", "中原", "少林", "美食", "文化", "交通枢纽"], "daily_cost": 350, "base_score": 7.8},
    "天津": {"tags": ["欧式", "海河", "相声", "美食", "近代", "休闲"], "daily_cost": 450, "base_score": 8.0},
    "济南": {"tags": ["泉水", "历史", "大明湖", "齐鲁", "文化", "休闲"], "daily_cost": 400, "base_score": 7.8},
    "珠海": {"tags": ["海滨", "休闲", "浪漫", "澳门", "度假", "情侣路"], "daily_cost": 500, "base_score": 8.0},
    "宁波": {"tags": ["港口", "历史", "海鲜", "天一阁", "江南", "商帮"], "daily_cost": 500, "base_score": 7.8},
    "福州": {"tags": ["榕城", "温泉", "三坊七巷", "闽菜", "历史", "休闲"], "daily_cost": 450, "base_score": 7.9},
    "合肥": {"tags": ["科教", "包公", "徽菜", "三国", "环湖", "休闲"], "daily_cost": 380, "base_score": 7.6},
    "佛山": {"tags": ["武术", "岭南", "祖庙", "美食", "陶瓷", "文化"], "daily_cost": 400, "base_score": 7.8},
    "无锡": {"tags": ["太湖", "园林", "鼋头渚", "灵山", "江南", "影视"], "daily_cost": 450, "base_score": 7.9},
    "贵阳": {"tags": ["山水", "避暑", "酸汤", "民俗", "甲秀楼", "休闲"], "daily_cost": 350, "base_score": 7.8},
}


@lru_cache(maxsize=1)
def _load_coords() -> dict:
    if not CITIES_FILE.exists():
        return {}
    return json.loads(CITIES_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_meta_json() -> dict:
    """加载 LLM 生成的城市画像。"""
    if not CITY_META_FILE.exists():
        return {}
    try:
        return json.loads(CITY_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_all_cities() -> list[str]:
    return list(_load_coords().keys())


def get_coord(city: str) -> tuple[float, float] | None:
    c = _load_coords().get(city)
    if not c:
        return None
    return (c["lng"], c["lat"])


def distance_km(city1: str, city2: str) -> float:
    c1 = get_coord(city1)
    c2 = get_coord(city2)
    if not c1 or not c2:
        return -1.0

    lng1, lat1 = math.radians(c1[0]), math.radians(c1[1])
    lng2, lat2 = math.radians(c2[0]), math.radians(c2[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def get_meta(city: str) -> dict:
    """城市元数据。优先级：
      1. LLM 生成的 city_meta.json
      2. 硬编码的 CORE_CITIES
      3. 默认值
    """
    json_meta = _load_meta_json()
    if city in json_meta:
        return json_meta[city]

    if city in CORE_CITIES:
        return CORE_CITIES[city]

    return {
        "tags": DEFAULT_TAGS,
        "daily_cost": DEFAULT_DAILY_COST,
        "base_score": DEFAULT_BASE_SCORE,
    }