"""持久化缓存 — SQLite 存储，重启不丢。"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path("data/cache.db")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            ts    REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def get(key: str, ttl: int) -> Optional[Any]:
    """读缓存。过期或不存在返回 None。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT value, ts FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        value_str, ts = row
        if time.time() - ts > ttl:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
            return None
        return json.loads(value_str)
    except Exception:
        return None
    finally:
        conn.close()


def set(key: str, value: Any) -> None:   # noqa: A001
    """写缓存。"""
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, ts) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def make_key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)