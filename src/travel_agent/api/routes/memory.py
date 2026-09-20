"""记忆管理 API：查询、写入、标记、清空。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


# ---------- 模型 ----------

class ProfilePayload(BaseModel):
    profile: dict = Field(default_factory=dict)


class MemoryItem(BaseModel):
    type: str                       # visited/liked/disliked/preference/note
    text: str
    metadata: dict = Field(default_factory=dict)


class AddMemoryPayload(BaseModel):
    items: list[MemoryItem]


class MarkPayload(BaseModel):
    poi_name: str
    city: str
    note: str = ""                   # liked/disliked 时的原因
    date: str = ""                   # visited 时的日期


class ExtractPayload(BaseModel):
    trip: dict = Field(default_factory=dict)
    feedback: str = ""


class SearchPayload(BaseModel):
    query: str
    k: int = 6


# ---------- 结构化画像 ----------

@router.get("/{user_id}/profile")
def get_profile(user_id: str):
    from ...memory.store import load_profile
    return load_profile(user_id)


@router.post("/{user_id}/profile")
def save_profile(user_id: str, payload: ProfilePayload):
    from ...memory.store import save_profile
    save_profile(user_id, payload.profile)
    return {"status": "saved"}


# ---------- 向量记忆 ----------

@router.get("/{user_id}/memories")
def list_memories(user_id: str, limit: int = 100):
    from ...memory.vector_store import list_memories
    return {"memories": list_memories(user_id, limit)}


@router.post("/{user_id}/memories")
def add_memories(user_id: str, payload: AddMemoryPayload):
    from ...memory.vector_store import add_memories_bulk
    n = add_memories_bulk(user_id, [i.model_dump() for i in payload.items])
    return {"added": n}


@router.delete("/{user_id}/memories/{memory_id}")
def delete_memory(user_id: str, memory_id: int):
    from ...memory.vector_store import delete_memory
    if not delete_memory(memory_id):
        raise HTTPException(404, "记忆不存在")
    return {"status": "deleted"}


@router.delete("/{user_id}/memories")
def clear_memories(user_id: str):
    from ...memory.vector_store import clear_user
    clear_user(user_id)
    return {"status": "cleared"}


# ---------- 语义检索 ----------

@router.post("/{user_id}/search")
def search(user_id: str, payload: SearchPayload):
    from ...memory.vector_store import search_memories
    return {"results": search_memories(user_id, payload.query, payload.k)}


# ---------- 快捷标记 ----------

@router.post("/{user_id}/mark/liked")
def mark_liked(user_id: str, payload: MarkPayload):
    from ...memory.memory_agent import mark_liked
    mid = mark_liked(user_id, payload.poi_name, payload.city, payload.note)
    return {"memory_id": mid}


@router.post("/{user_id}/mark/disliked")
def mark_disliked(user_id: str, payload: MarkPayload):
    from ...memory.memory_agent import mark_disliked
    mid = mark_disliked(user_id, payload.poi_name, payload.city, payload.note)
    return {"memory_id": mid}


@router.post("/{user_id}/mark/visited")
def mark_visited(user_id: str, payload: MarkPayload):
    from ...memory.memory_agent import mark_visited
    mid = mark_visited(user_id, payload.poi_name, payload.city, payload.date)
    return {"memory_id": mid}


# ---------- 行程结束后提取 ----------

@router.post("/{user_id}/extract")
def extract(user_id: str, payload: ExtractPayload):
    from ...memory.memory_agent import extract_and_save
    n = extract_and_save(user_id, payload.trip, payload.feedback)
    return {"extracted": n}