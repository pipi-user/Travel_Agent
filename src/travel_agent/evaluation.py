"""行程质量评估体系 — 多维度评分。

评估指标：
  1. diversity_score:    POI 类型多样性（景点/餐厅/酒店分布）
  2. geo_score:          地理合理性（同天景点距离是否合理）
  3. budget_score:       预算匹配度（总费用 vs 用户预算）
  4. time_score:         时间利用率（每天时段是否填满）
  5. preference_score:   偏好匹配度（是否符合用户偏好标签）

综合分 = 加权平均
"""
import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)


def evaluate_itinerary(
    itinerary: list[dict],
    user_info: dict,
    all_pois: Optional[list[dict]] = None,
) -> dict:
    """评估行程质量，返回各维度分数 + 综合分。

    Args:
        itinerary: 行程列表 [{day, items: [{poi_id, name, period, poi_type, cost, lat, lng, ...}], total_cost}]
        user_info: 用户信息 {dest_city, budget, days, preferences, ...}
        all_pois: 全部 POI 池（用于计算覆盖率）

    Returns:
        {diversity_score, geo_score, budget_score, time_score, preference_score, overall, summary}
    """
    if not itinerary:
        return {"overall": 0, "summary": "行程为空"}

    scores = {
        "diversity_score": _eval_diversity(itinerary),
        "geo_score": _eval_geo_coherence(itinerary),
        "budget_score": _eval_budget_match(itinerary, user_info),
        "time_score": _eval_time_utilization(itinerary, user_info),
        "preference_score": _eval_preference_match(itinerary, user_info, all_pois),
    }

    # 加权平均
    weights = {
        "diversity_score": 0.20,
        "geo_score": 0.25,
        "budget_score": 0.20,
        "time_score": 0.15,
        "preference_score": 0.20,
    }
    overall = sum(scores[k] * weights[k] for k in weights)
    scores["overall"] = round(overall, 2)
    scores["summary"] = _generate_summary(scores)
    return scores


# ─── 各维度评分函数 ──────────────────────────────────

def _eval_diversity(itinerary: list[dict]) -> float:
    """POI 类型多样性（0-1）。类型越均匀分数越高。"""
    type_counts = {}
    total = 0
    for day in itinerary:
        for item in day.get("items", []):
            t = item.get("poi_type", "other")
            type_counts[t] = type_counts.get(t, 0) + 1
            total += 1

    if total == 0:
        return 0.0

    # 类型数量
    n_types = len(type_counts)
    if n_types <= 1:
        return 0.3

    # 均匀度（熵 / 最大熵）
    entropy = -sum((c / total) * math.log2(c / total) for c in type_counts.values() if c > 0)
    max_entropy = math.log2(n_types) if n_types > 1 else 1
    uniformity = entropy / max_entropy if max_entropy > 0 else 0

    # 类型覆盖度（至少要有 attraction + food）
    has_attraction = "attraction" in type_counts
    has_food = "food" in type_counts
    coverage_bonus = 0.2 * (int(has_attraction) + int(has_food)) / 2

    return round(min(1.0, uniformity * 0.7 + coverage_bonus + 0.1 * min(n_types / 4, 1)), 2)


def _eval_geo_coherence(itinerary: list[dict]) -> float:
    """地理合理性（0-1）。同天景点之间的距离是否合理。"""
    total_score = 0
    n_days = 0

    for day in itinerary:
        items = day.get("items", [])
        coords = [(it.get("lat", 0), it.get("lng", 0)) for it in items if it.get("lat") and it.get("lng")]
        if len(coords) < 2:
            continue

        n_days += 1
        # 计算相邻点距离之和
        total_dist = 0
        for i in range(len(coords) - 1):
            dist = _haversine(coords[i], coords[i + 1])
            total_dist += dist

        # 平均相邻距离（km）
        avg_dist = total_dist / (len(coords) - 1)

        # 理想平均距离：城市内 3-10km 最佳
        if avg_dist <= 1:
            day_score = 0.6  # 太近
        elif avg_dist <= 5:
            day_score = 1.0  # 理想
        elif avg_dist <= 15:
            day_score = 0.8  # 可接受
        elif avg_dist <= 30:
            day_score = 0.5  # 偏远
        else:
            day_score = 0.2  # 太远

        total_score += day_score

    return round(total_score / n_days, 2) if n_days > 0 else 0.5


def _eval_budget_match(itinerary: list[dict], user_info: dict) -> float:
    """预算匹配度（0-1）。总费用 vs 用户预算。"""
    budget = user_info.get("budget")
    if not budget or budget <= 0:
        return 0.7  # 无预算信息，给默认分

    total_cost = sum(day.get("total_cost", 0) for day in itinerary)
    if total_cost == 0:
        return 0.5  # 无费用数据

    ratio = total_cost / budget

    if ratio <= 0.5:
        return 0.6  # 远低于预算，可能遗漏了内容
    elif ratio <= 0.85:
        return 1.0  # 理想：充分利用预算
    elif ratio <= 1.0:
        return 0.9  # 刚好
    elif ratio <= 1.2:
        return 0.6  # 略超
    else:
        return 0.3  # 严重超预算


def _eval_time_utilization(itinerary: list[dict], user_info: dict) -> float:
    """时间利用率（0-1）。每天时段是否填满。"""
    expected_periods = {"morning", "noon", "afternoon", "evening"}
    total_score = 0
    n_days = 0

    for day in itinerary:
        items = day.get("items", [])
        if not items:
            continue
        n_days += 1
        covered = {it.get("period") for it in items if it.get("period")}
        coverage = len(covered & expected_periods) / len(expected_periods)
        total_score += min(1.0, coverage * 1.1)  # 稍微奖励覆盖 3/4 的

    return round(total_score / n_days, 2) if n_days > 0 else 0.0


def _eval_preference_match(
    itinerary: list[dict],
    user_info: dict,
    all_pois: Optional[list[dict]] = None,
) -> float:
    """偏好匹配度（0-1）。行程是否符合用户偏好。"""
    preferences = user_info.get("preferences", [])
    if not preferences:
        return 0.7  # 无偏好信息，给默认分

    # 简单匹配：检查 POI 名称/类型是否包含偏好关键词
    all_names = " ".join(
        it.get("name", "") + " " + it.get("poi_type", "")
        for day in itinerary
        for it in day.get("items", [])
    )

    matched = sum(1 for p in preferences if p in all_names)
    ratio = matched / len(preferences) if preferences else 0

    return round(min(1.0, ratio + 0.3), 2)  # 基础分 0.3


# ─── 辅助函数 ──────────────────────────────────────

def _haversine(coord1: tuple, coord2: tuple) -> float:
    """计算两个经纬度坐标之间的距离（km）。"""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371  # 地球半径 km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _generate_summary(scores: dict) -> str:
    """生成评估摘要文本。"""
    overall = scores["overall"]
    parts = []

    if overall >= 0.85:
        parts.append("✨ 行程质量优秀！")
    elif overall >= 0.7:
        parts.append("👍 行程质量不错。")
    elif overall >= 0.5:
        parts.append("🤔 行程还可以优化。")
    else:
        parts.append("⚠️ 行程质量偏低，建议调整。")

    # 找出最弱的维度
    dims = {
        "diversity_score": "类型多样性",
        "geo_score": "地理合理性",
        "budget_score": "预算匹配",
        "time_score": "时间利用",
        "preference_score": "偏好匹配",
    }
    weak = min(dims, key=lambda k: scores.get(k, 1))
    if scores.get(weak, 1) < 0.6:
        parts.append(f"建议优化：{dims[weak]}（{scores[weak]:.0%}）")

    return " ".join(parts)
