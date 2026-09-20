"""基于 sqlite-vec 的向量记忆存储。"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import sqlite_vec

from .embeddings import embed, EMBED_DIM

DB_PATH = Path("data/memory_vec.db")


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
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        type TEXT NOT NULL,
        text TEXT NOT NULL,
        metadata TEXT DEFAULT '{{}}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id);
    CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(user_id, type);

    CREATE VIRTUAL TABLE IF NOT EXISTS memory_vecs USING vec0(
        memory_id INTEGER PRIMARY KEY,
        embedding FLOAT[{EMBED_DIM}]
    );
    """)
    conn.commit()


# ---------- 写入 ----------

def add_memory(
    user_id: str,
    type_: str,
    text: str,
    metadata: dict | None = None,
) -> int:
    """写一条记忆 + 向量索引。返回 memory_id。"""
    if not text.strip():
        return -1

    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO memories (user_id, type, text, metadata) VALUES (?, ?, ?, ?)",
            (user_id, type_, text, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        mem_id = cur.lastrowid
        vec = embed(text)
        conn.execute(
            "INSERT INTO memory_vecs (memory_id, embedding) VALUES (?, ?)",
            (mem_id, sqlite_vec.serialize_float32(vec)),
        )
        conn.commit()
        return mem_id
    except Exception:
        conn.rollback()
        return -1
    finally:
        conn.close()


def add_memories_bulk(user_id: str, items: list[dict]) -> int:
    """批量写入。items: [{"type": ..., "text": ..., "metadata": {...}}]"""
    if not items:
        return 0
    conn = _conn()
    n = 0
    try:
        for item in items:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            cur = conn.execute(
                "INSERT INTO memories (user_id, type, text, metadata) VALUES (?, ?, ?, ?)",
                (
                    user_id,
                    item.get("type", "note"),
                    text,
                    json.dumps(item.get("metadata", {}), ensure_ascii=False),
                ),
            )
            vec = embed(text)
            conn.execute(
                "INSERT INTO memory_vecs (memory_id, embedding) VALUES (?, ?)",
                (cur.lastrowid, sqlite_vec.serialize_float32(vec)),
            )
            n += 1
        conn.commit()
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()
    return n


# ---------- 查询 ----------

def search_memories(
    user_id: str,
    query: str,
    k: int = 5,
    types: list[str] | None = None,
) -> list[dict]:
    """语义检索 Top-K。"""
    if not query.strip():
        return []

    qvec = sqlite_vec.serialize_float32(embed(query))
    conn = _conn()
    try:
        # sqlite-vec KNN 先取多一点，再在 Python 里过滤 user/type
        rows = conn.execute(
            """
            SELECT m.id, m.user_id, m.type, m.text, m.metadata, v.distance
            FROM memory_vecs v
            JOIN memories m ON m.id = v.memory_id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (qvec, k * 10),
        ).fetchall()
    except Exception:
        conn.close()
        return []

    results = []
    for rid, uid, type_, text, meta, dist in rows:
        if uid != user_id:
            continue
        if types and type_ not in types:
            continue
        results.append({
            "id": rid,
            "type": type_,
            "text": text,
            "metadata": json.loads(meta or "{}"),
            "score": round(1.0 - float(dist), 3),
        })
        if len(results) >= k:
            break

    conn.close()
    return results


def list_memories(user_id: str, limit: int = 100) -> list[dict]:
    """列出用户所有记忆（管理用）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT id, type, text, metadata, created_at
               FROM memories WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "id": r[0], "type": r[1], "text": r[2],
            "metadata": json.loads(r[3] or "{}"),
            "created_at": r[4],
        }
        for r in rows
    ]


def delete_memory(memory_id: int) -> bool:
    conn = _conn()
    try:
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.execute("DELETE FROM memory_vecs WHERE memory_id = ?", (memory_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def clear_user(user_id: str) -> bool:
    """清空某用户全部记忆。"""
    conn = _conn()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM memories WHERE user_id = ?", (user_id,)
        ).fetchall()]
        conn.executemany("DELETE FROM memory_vecs WHERE memory_id = ?",
                         [(i,) for i in ids])
        conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()