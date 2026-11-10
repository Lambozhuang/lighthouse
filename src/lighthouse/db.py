"""Postgres access.

Two ways to get a connection:

- `user_conn(user_id)`: for anything done on behalf of a signed-in user. The transaction runs as
  role `authenticated` with the user's id in `request.jwt.claims`, exactly what PostgREST does,
  so `auth.uid()` works and the row level security policies decide what is visible.
- `service_conn()`: for the worker and migrations. Runs as the table owner, which bypasses RLS,
  so every query here must filter by user_id itself.
"""

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

Conn = AsyncConnection[DictRow]

_pool: AsyncConnectionPool[Conn] | None = None


async def open_pool(database_url: str, *, max_size: int = 10) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = AsyncConnectionPool(
        database_url,
        connection_class=AsyncConnection[DictRow],
        kwargs={"row_factory": dict_row, "autocommit": True},
        min_size=1,
        max_size=max_size,
        open=False,
    )
    await _pool.open()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool[Conn]:
    if _pool is None:
        raise RuntimeError("database pool is not open")
    return _pool


@asynccontextmanager
async def user_conn(user_id: UUID) -> AsyncIterator[Conn]:
    """One transaction, run as `user_id` under row level security."""
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    async with pool().connection() as conn, conn.transaction():
        # set_config(..., true) is SET LOCAL: both settings end with the transaction.
        await conn.execute(
            "select set_config('request.jwt.claims', %s, true), set_config('role', 'authenticated', true)",
            [claims],
        )
        yield conn


@asynccontextmanager
async def service_conn() -> AsyncIterator[Conn]:
    """One transaction as the table owner. Bypasses RLS: always filter by user_id."""
    async with pool().connection() as conn, conn.transaction():
        yield conn


def to_vector(values: Sequence[float]) -> str:
    """pgvector's text form; pass as a parameter and cast with `%s::vector`."""
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


async def fetch_all(conn: Conn, query: str, params: Sequence[Any] = ()) -> list[DictRow]:
    cur = await conn.execute(query, params)  # pyright: ignore[reportArgumentType, reportCallIssue]
    return await cur.fetchall()


async def fetch_one(conn: Conn, query: str, params: Sequence[Any] = ()) -> DictRow | None:
    cur = await conn.execute(query, params)  # pyright: ignore[reportArgumentType, reportCallIssue]
    return await cur.fetchone()
