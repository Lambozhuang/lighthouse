"""Test fixtures. Tests need a Postgres with pgvector:

    docker run -d --name lighthouse-test-db -e POSTGRES_PASSWORD=postgres -p 54330:5432 pgvector/pgvector:pg17

Each test session creates its own throwaway database on that server, loads a small Supabase
stand-in (roles, auth.users, auth.uid()) and applies the real migrations.
"""

import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import httpx
import jwt
import psycopg
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:54330/postgres")
TEST_JWT_SECRET = "test-secret-not-used-anywhere-else-0123456789"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    name = f"lighthouse_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')  # pyright: ignore[reportArgumentType, reportCallIssue]
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute((ROOT / "tests/sql/supabase_stub.sql").read_text())  # pyright: ignore[reportArgumentType, reportCallIssue]
    yield url
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{name}" with (force)')  # pyright: ignore[reportArgumentType, reportCallIssue]


@pytest.fixture(scope="session", autouse=True)
def settings_env(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["JWT_SECRET"] = TEST_JWT_SECRET
    os.environ["LANGFUSE_PUBLIC_KEY"] = ""
    os.environ["LANGFUSE_SECRET_KEY"] = ""
    from lighthouse.config import get_settings

    get_settings.cache_clear()


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def database(database_url: str, settings_env: None) -> AsyncIterator[None]:
    from lighthouse import db
    from lighthouse.agent import graph
    from lighthouse.migrate import migrate

    await migrate(database_url, ROOT / "supabase/migrations")
    await db.open_pool(database_url)
    await graph.open_agent(database_url)
    yield
    await graph.close_agent()
    await db.close_pool()


async def _create_user() -> UUID:
    from lighthouse import db

    async with db.service_conn() as conn:
        row = await db.fetch_one(
            conn, "insert into auth.users (email) values (%s) returning id", [f"{uuid.uuid4().hex}@example.com"]
        )
    assert row is not None
    return row["id"]


@pytest_asyncio.fixture(loop_scope="session")
async def user_id() -> UUID:
    return await _create_user()


@pytest_asyncio.fixture(loop_scope="session")
async def other_user_id() -> UUID:
    return await _create_user()


def token_for(user_id: UUID) -> str:
    now = int(time.time())
    claims = {"sub": str(user_id), "aud": "authenticated", "role": "authenticated", "iat": now, "exp": now + 600}
    return jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")


def auth_headers(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user_id)}"}


@pytest_asyncio.fixture(loop_scope="session")
async def client(database: None) -> AsyncIterator[httpx.AsyncClient]:
    """Calls the FastAPI app in-process. The pools are already open, so lifespan is not run."""
    from lighthouse.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
