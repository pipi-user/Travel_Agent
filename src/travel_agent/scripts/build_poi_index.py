"""一次性构建 POI 向量索引。

用法：
    uv run python src/travel_agent/scripts/build_poi_index.py 汕头
    uv run python src/travel_agent/scripts/build_poi_index.py 汕头 成都 广州
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.travel_agent.agents.poi_collector import collect_pois_v2
from src.travel_agent.memory.poi_vector_store import index_pois, count_pois


def main():
    cities = sys.argv[1:] if len(sys.argv) > 1 else ["汕头"]

    print(f"准备为 {len(cities)} 个城市构建索引：{cities}\n")

    for city in cities:
        print(f"── {city} ──")
        print(f"  采集 POI（首次约 3-7 分钟）...")

        result = collect_pois_v2(
            city=city, budget=5000, companions=2,
            days=3, intensity="莫名其妙地玩", preferences=[],
        )

        pois = result.get("pois", [])
        print(f"  拿到 {len(pois)} 条 POI，正在向量化...")

        n = index_pois(pois, city)
        print(f"  ✅ 写入 {n} 条，累计该城市 {count_pois(city)} 条\n")

    print("完成。")


if __name__ == "__main__":
    main()