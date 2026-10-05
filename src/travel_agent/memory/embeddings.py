"""Embedding 封装：OpenAI 兼容 API，带缓存。"""
import hashlib
from langchain_openai import OpenAIEmbeddings

from ..cache import get as cache_get, set as cache_set, make_key
from ..config import settings

# 阿里百炼：text-embedding-v3（1536 维）
# OpenAI：text-embedding-3-small（1536 维）
EMBED_MODEL = "text-embedding-v3"
EMBED_DIM = 1024

_emb = None


def _get() -> OpenAIEmbeddings:
    global _emb
    if _emb is None:
        _emb = OpenAIEmbeddings(
            model=EMBED_MODEL,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            dimensions=EMBED_DIM,
            check_embedding_ctx_length=False,
        )
    return _emb


def embed(text: str) -> list[float]:
    """单条文本 → 向量。失败返回零向量，不阻塞主流程。"""
    if not text or not text.strip():
        return [0.0] * EMBED_DIM

    key = make_key("embed", hashlib.md5(text.encode()).hexdigest())
    hit = cache_get(key, 86400 * 7)
    if hit is not None:
        return hit

    try:
        vec = _get().embed_query(text[:8000])
        cache_set(key, vec)
        return vec
    except Exception as e:
        import traceback
        print(f"[embed] 失败: {e}")
        traceback.print_exc()
        return [0.0] * EMBED_DIM
       

def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量向量化。"""
    if not texts:
        return []
    try:
        return _get().embed_documents([t[:8000] for t in texts])
    except Exception:
        return [[0.0] * EMBED_DIM for _ in texts]