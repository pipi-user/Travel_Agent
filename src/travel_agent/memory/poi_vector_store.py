"""POI 向量库 — 语义搜索景点/美食/酒店。

独立存储于 data/poi_vec.db，与用户记忆库分离。
"""
import json
import sqlite3
from pathlib import Path

import sqlite_vec

from .embeddings import embed, EMBED_DIM

DB_PATH = Path("data/poi_vec.db")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    _init(conn)
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS poi_meta (
        poi_id TEXT PRIMARY KEY,
        city TEXT NOT NULL,
        name TEXT NOT NULL,
        poi_type TEXT,
        tags TEXT,
        desc TEXT,
        cost REAL,
        duration INTEGER,
        lat REAL,
        lng REAL,
        image_url TEXT,
        address TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_poi_city ON poi_meta(city);

    CREATE VIRTUAL TABLE IF NOT EXISTS poi_vecs USING vec0(
        poi_id TEXT PRIMARY KEY,
        embedding FLOAT[{EMBED_DIM}]
    );
    """)
    conn.commit()


def index_pois(pois: list[dict], city: str) -> int:
    """批量写入 POI 到向量库。返回写入条数。"""
    if not pois:
        return 0

    conn = _conn()
    n = 0
    try:
        for p in pois:
            text = _poi_to_text(p)
            vec = embed(text)

            conn.execute(
                """INSERT OR REPLACE INTO poi_meta
                   (poi_id, city, name, poi_type, tags, desc, cost, duration, lat, lng, image_url, address)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["id"], city, p["name"], p.get("poi_type", ""),
                    json.dumps(p.get("tags", []), ensure_ascii=False),
                    p.get("desc", ""),
                    float(p.get("cost", 0) or 0),
                    int(p.get("duration", 90) or 90),
                    float(p.get("lat", 0) or 0),
                    float(p.get("lng", 0) or 0),
                    p.get("image_url", ""),
                    p.get("address", ""),
                ),
            )

            conn.execute(
                "INSERT OR REPLACE INTO poi_vecs (poi_id, embedding) VALUES (?, ?)",
                (p["id"], sqlite_vec.serialize_float32(vec)),
            )
            n += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[poi_vector_store] 写入失败：{e}")
        return 0
    finally:
        conn.close()
    return n


def search_pois(query: str, city: str = "", k: int = 10) -> list[dict]:
    """语义搜索 POI。返回 Top-K。"""
    if not query.strip():
        return []

    qvec = sqlite_vec.serialize_float32(embed(query))
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT m.poi_id, m.name, m.poi_type, m.tags, m.desc,
                   m.cost, m.duration, m.lat, m.lng, m.image_url, m.address,
                   v.distance
            FROM poi_vecs v
            JOIN poi_meta m ON m.poi_id = v.poi_id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (qvec, k * 3),
        ).fetchall()
    except Exception as e:
        print(f"[poi_vector_store] 检索失败：{e}")
        conn.close()
        return []

    results = []
    for row in rows:
        (pid, name, ptype, tags_json, desc, cost, dur,
         lat, lng, img, addr, dist) = row

        # 按城市过滤
        if city:
            city_check = conn.execute(
                "SELECT city FROM poi_meta WHERE poi_id = ?", (pid,)
            ).fetchone()
            if not city_check or city_check[0] != city:
                continue

        results.append({
            "id": pid,
            "name": name,
            "poi_type": ptype,
            "tags": json.loads(tags_json or "[]"),
            "desc": desc,
            "cost": cost,
            "duration": dur,
            "lat": lat,
            "lng": lng,
            "image_url": img,
            "address": addr,
            "_raw_dist": float(dist),      # ⭐ 临时存原始距离
        })
        if len(results) >= k:
            break

    conn.close()

    # ⭐ 归一化：把距离映射到 [0.6, 0.95]
    if results:
        dists = [r["_raw_dist"] for r in results]
        d_min, d_max = min(dists), max(dists)
        span = (d_max - d_min) if d_max > d_min else 1.0
        for r in results:
            norm = 1.0 - (r["_raw_dist"] - d_min) / span
            r["score"] = round(0.6 + norm * 0.35, 3)
            del r["_raw_dist"]

    return results


def count_pois(city: str = "") -> int:
    """统计 POI 数。"""
    conn = _conn()
    try:
        if city:
            row = conn.execute(
                "SELECT COUNT(*) FROM poi_meta WHERE city = ?", (city,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM poi_meta").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def clear_city(city: str) -> int:
    """清空某城市的 POI。"""
    conn = _conn()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT poi_id FROM poi_meta WHERE city = ?", (city,)
        ).fetchall()]
        for pid in ids:
            conn.execute("DELETE FROM poi_vecs WHERE poi_id = ?", (pid,))
        conn.execute("DELETE FROM poi_meta WHERE city = ?", (city,))
        conn.commit()
        return len(ids)
    finally:
        conn.close()


def _poi_to_text(p: dict) -> str:
    """POI → 用于向量化的文本。"""
    parts = [p.get("name", "")]
    if p.get("desc"):
        parts.append(p["desc"])
    if p.get("tags"):
        parts.append("标签：" + "、".join(p["tags"]))
    if p.get("address"):
        parts.append("地址：" + p["address"])
    return "。".join(parts)