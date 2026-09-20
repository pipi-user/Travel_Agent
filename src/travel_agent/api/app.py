"""FastAPI 应用实例 — 灵感漫游 v2。

启动：
    uv run uvicorn travel_agent.api:app --reload
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import memory
from .routes import explore
from .routes import plan
from .routes import inspire
# from .routes import target  # 暂时禁用，缺少模型定义

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Travel Agent API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:5176", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(explore.router, prefix="/api/explore", tags=["explore"])
app.include_router(plan.router,    prefix="/api/plan",    tags=["plan"])
# app.include_router(target.router,  prefix="/api/target",  tags=["target"])
app.include_router(memory.router,  prefix="/api/memory",  tags=["memory"])
app.include_router(inspire.router, prefix="/api/inspire", tags=["inspire"])


@app.get("/")
def root():
    return {"status": "ok", "service": "travel-agent-api", "version": "2.0.0"}
