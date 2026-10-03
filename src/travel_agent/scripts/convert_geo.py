"""ok_geo.csv → data/cities.json"""
import csv
csv.field_size_limit(2**31 - 1)

import json
from pathlib import Path
import pandas as pd

INPUT = Path(r"C:\Users\唔系迪西\Desktop\ok_geo.csv\ok_geo.csv")
OUTPUT = Path("data/cities.json")


def main():
    if not INPUT.exists():
        print(f"❌ 找不到 {INPUT}")
        return

    print(f"读取 {INPUT} ...")
    df = pd.read_csv(
        INPUT, encoding="utf-8-sig", dtype=str,
        usecols=["deep", "name", "geo"], engine="c",
    )
    print(f"总行数：{len(df)}")

    df = df[df["deep"] == "1"]
    print(f"地级市行数：{len(df)}")

    cities = {}
    skipped = 0
    skipped_names = [] 
    for _, row in df.iterrows():
        name = str(row["name"] or "").strip().rstrip("市")
        geo = str(row["geo"] or "").strip()

        # ⭐ 空格或逗号都行
        geo_parts = geo.replace(",", " ").split()
        if not name or len(geo_parts) < 2:
            skipped += 1
            continue

        try:
            lng_s, lat_s = geo_parts[0], geo_parts[1]
            cities[name] = {
                "lat": round(float(lat_s), 6),
                "lng": round(float(lng_s), 6),
            }
        except (ValueError, IndexError):
            skipped += 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(cities, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ 写入 {len(cities)} 个城市 → {OUTPUT}")
    if skipped:
        print(f"⚠️ 跳过 {skipped} 行")


if __name__ == "__main__":
    main()