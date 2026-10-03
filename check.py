import sqlite3
from pathlib import Path

for db_file in ["data/memory_vec.db", "data/cache.db"]:
    p = Path(db_file)
    if not p.exists():
        print(f"\n{db_file} —— 不存在")
        continue

    conn = sqlite3.connect(str(p))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    conn.close()

    print(f"\n{db_file} 里的表:")
    for t in tables:
        print("  -", t[0])