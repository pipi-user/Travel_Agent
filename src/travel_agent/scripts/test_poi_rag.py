"""测试 POI RAG 语义搜索。"""
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.travel_agent.memory.poi_vector_store import search_pois, count_pois


def main():
    print(f"向量库总 POI 数：{count_pois()}\n")

    queries = [
        ("汕头", "安静的咖啡馆"),
        ("汕头", "本地人爱吃的小吃"),
        ("汕头", "拍照好看的地方"),
        ("汕头", "历史文化古迹"),
        ("汕头", "适合带孩子的地方"),
    ]

    for city, q in queries:
        print(f"── 搜索：{q} （{city}）──")
        results = search_pois(q, city, k=5)
        if not results:
            print("  （无结果）\n")
            continue
        for i, r in enumerate(results, 1):
            print(f"  {i}. {r['name']}  [score={r['score']}]")
            print(f"     标签：{'、'.join(r['tags'])}")
            print(f"     简介：{r['desc'][:50]}")
        print()


if __name__ == "__main__":
    main()