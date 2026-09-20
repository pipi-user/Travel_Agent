"""进程内缓存。够用，部署多实例时换成 Redis 即可。"""
import time
from typing import Any, Optional

_store: dict[str, tuple[float, Any]] = {}


def get(key: str, ttl: int) -> Optional[Any]:
    item = _store.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > ttl:
        _store.pop(key, None)
        return None
    return val


def set(key: str, value: Any) -> None:   # noqa: A001
    _store[key] = (time.time(), value)


def make_key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)