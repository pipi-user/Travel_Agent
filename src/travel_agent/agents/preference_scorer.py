"""偏好标签权重 — 用户偏好匹配度加权排序，不删除只排序。

每个 POI 自带 tags 标签集合；用户偏好标签匹配度低的 POI 权重降低，
排在列表靠后；完全无关 POI 少量保留，不全部删除。
"""
import logging

logger = logging.getLogger(__name__)

# 用户偏好 → POI 标签 匹配映射
PREFERENCE_TAG_MAP: dict[str, list[str]] = {
    "人文":   ["历史", "文化", "古迹", "博物馆", "古镇", "非遗", "民俗"],
    "自然":   ["山水", "公园", "湖", "森林", "瀑布", "海滩", "温泉", "草原"],
    "历史":   ["历史", "古迹", "遗址", "古城", "博物馆", "文物"],
    "美食":   ["本地菜", "小吃", "特色餐", "夜市", "美食街", "老字号"],
    "购物":   ["商场", "步行街", "特产", "免税", "集市"],
    "摄影":   ["日出", "日落", "夜景", "花海", "梯田", "星空", "红墙"],
    "冒险":   ["漂流", "攀岩", "蹦极", "滑翔", "徒步", "探险", "越野"],
    "休闲":   ["温泉", "度假", "茶馆", "咖啡", "慢生活", "养生"],
}


def _tag_matches(preference: str, poi_tags: list[str]) -> bool:
    """检查 POI 标签是否匹配某个用户偏好。"""
    mapped = PREFERENCE_TAG_MAP.get(preference, [])
    if not mapped:
        # 未定义的偏好直接做字符串匹配
        return any(preference in t or t in preference for t in poi_tags)
    return any(tag in poi_tags for tag in mapped)


def score_by_preference(
    pois: list[dict],
    preferences: list[str],
) -> list[dict]:
    """偏好匹配加权排序。

    - 匹配度高的 POI 权重 1.5，排在前面
    - 不匹配的保持 1.0，排在后面
    - 不删除任何 POI
    """
    if not preferences:
        return pois

    for poi in pois:
        poi_tags = poi.get("tags", [])
        weight = 1.0
        for pref in preferences:
            if _tag_matches(pref, poi_tags):
                weight = max(weight, 1.5)
        poi["_pref_weight"] = weight

    # 稳定排序：权重高的在前
    pois.sort(key=lambda x: -x.get("_pref_weight", 1.0))

    matched = sum(1 for p in pois if p.get("_pref_weight", 1.0) > 1.0)
    logger.info("偏好排序：%d 个偏好，%d/%d 条 POI 匹配",
                len(preferences), matched, len(pois))
    return pois
