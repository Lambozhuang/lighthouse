"""The API service.  uvicorn lighthouse.main:app --port 8080"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lighthouse import db
from lighthouse.agent import graph
from lighthouse.api import chat, inbox, notes, threads
from lighthouse.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.open_pool(get_settings().database_url)
    # The chat agent's checkpointer has a pool of its own (see lighthouse.agent.graph).
    await graph.open_agent(get_settings().database_url)
    try:
        yield
    finally:
        await graph.close_agent()
        await db.close_pool()


app = FastAPI(title="Lighthouse", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
async def health() -> dict[str, str]:
    async with db.service_conn() as conn:
        await conn.execute("select 1")
    return {"status": "ok"}


app.include_router(inbox.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(threads.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
