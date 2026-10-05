"""一次性调用 LLM 给 372 个城市生成画像（tags + daily_cost + base_score）。

用法：
    uv run python src/travel_agent/scripts/generate_city_meta.py
    uv run python src/travel_agent/scripts/generate_city_meta.py --force  # 强制重跑
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.travel_agent.agents.city_meta import get_all_cities
from src.travel_agent.llm import get_llm

OUTPUT = Path("data/city_meta.json")
BATCH_SIZE = 15          # 每批 15 个城市
SLEEP_BETWEEN = 0.5      # 批次间休眠，避免限流


def _load_existing() -> dict:
    if OUTPUT.exists():
        return json.loads(OUTPUT.read_text(encoding="utf-8"))
    return {}


def _save(data: dict) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_prompt(cities: list[str]) -> str:
    return f"""你是中国城市旅游画像专家。给以下 {len(cities)} 个城市生成旅游画像。

【城市列表】
{json.dumps(cities, ensure_ascii=False)}

【输出格式】
严格返回 JSON 数组，每个元素：
{{
  "city": "城市名",
  "tags": ["标签1", "标签2", "标签3", "标签4"],
  "daily_cost": 400,
  "base_score": 7.5
}}

【字段规则】
1. tags：3-5 个旅游相关标签，从以下词库选（可组合）：
   类别：美食 / 自然 / 历史 / 文化 / 购物 / 摄影 / 冒险 / 休闲 / 人文 / 海滨
   特色：古城 / 山水 / 温泉 / 草原 / 沙漠 / 雪景 / 民族 / 边境 / 小众 / 网红 / 亲子
   菜系：火锅 / 海鲜 / 小吃 / 烧烤 / 早茶 / 面食 / 粤菜 / 川菜 / 湘菜 / 西北菜
2. daily_cost：人均日消费（元，含吃住行，不含城际交通），整数。
   一线城市 600-800，省会/热门 400-600，地级市 300-450，边境小城 250-400。
3. base_score：旅游热度分（6.0-9.5），
   北京/上海/成都/西安等 9.0+，热门网红城市 8.0-8.8，普通地级市 6.5-7.5。

【示例】
[
  {{"city": "汕头", "tags": ["美食", "海鲜", "小吃", "古城"], "daily_cost": 350, "base_score": 8.0}},
  {{"city": "喀什", "tags": ["民族", "边境", "历史", "小众"], "daily_cost": 300, "base_score": 7.5}},
  {{"city": "哈尔滨", "tags": ["雪景", "俄式", "历史", "美食"], "daily_cost": 400, "base_score": 8.2}}
]

只输出 JSON 数组，不要解释、不要 markdown 代码块。"""


def _call_llm(cities: list[str]) -> list[dict]:
    """调 LLM 生成一批。失败返回空列表。"""
    llm = get_llm(json_mode=True)
    prompt = _build_prompt(cities)

    try:
        resp = llm.invoke(prompt)
        content = resp.content.strip()
        # 清 markdown 包裹
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content
            content = content.rsplit("```", 1)[0]
        content = content.strip()
        # 取第一个 [ 到最后一个 ]
        s, e = content.find("["), content.rfind("]")
        if s != -1 and e != -1:
            content = content[s:e + 1]
        data = json.loads(content)
        if not isinstance(data, list):
            return []
        return data
    except Exception as ex:
        print(f"    [失败] {ex}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制重跑（覆盖已有）")
    args = parser.parse_args()

    all_cities = get_all_cities()
    print(f"总城市数：{len(all_cities)}")

    existing = {} if args.force else _load_existing()
    print(f"已有画像：{len(existing)}")

    todo = [c for c in all_cities if c not in existing]
    print(f"待生成：{len(todo)}\n")

    if not todo:
        print("全部已完成。")
        return

    batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]

    for i, batch in enumerate(batches, 1):
        print(f"[{i}/{len(batches)}] 处理 {len(batch)} 个城市...")
        print(f"  {batch}")

        result = _call_llm(batch)
        if not result:
            print("  跳过\n")
            continue

        for item in result:
            if not isinstance(item, dict):
                continue
            city = item.get("city", "").strip()
            if not city or city not in all_cities:
                continue
            tags = item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            existing[city] = {
                "tags": [str(t) for t in tags[:5]],
                "daily_cost": int(item.get("daily_cost", 400)),
                "base_score": float(item.get("base_score", 7.0)),
            }

        _save(existing)
        print(f"  ✅ 累计 {len(existing)}/{len(all_cities)}\n")
        time.sleep(SLEEP_BETWEEN)

    print(f"\n完成。共 {len(existing)} 个城市画像 → {OUTPUT}")


if __name__ == "__main__":
    main()