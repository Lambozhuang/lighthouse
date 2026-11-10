"""The parts everything else stands on: migrations, auth, row level security."""

from uuid import UUID

import httpx
import pytest

from lighthouse import db
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio(loop_scope="session")

VECTOR = db.to_vector([0.1] * 1536)


async def _insert_note(user_id: UUID, title: str) -> UUID:
    async with db.service_conn() as conn:
        note = await db.fetch_one(
            conn,
            "insert into notes (user_id, title, summary, body, tags) values (%s, %s, %s, %s, %s) returning id",
            [user_id, title, f"summary of {title}", "body", ["demo"]],
        )
        assert note is not None
        await conn.execute(
            "insert into note_chunks (note_id, user_id, kind, chunk_index, content, embedding) "
            "values (%s, %s, 'distilled', 0, %s, %s::vector)",
            [note["id"], user_id, f"{title} sleep before eleven", VECTOR],
        )
    return note["id"]


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200


async def test_requires_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/notes")).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert (await client.get("/api/notes", headers=bad)).status_code == 401


async def test_notes_are_isolated_per_user(client: httpx.AsyncClient, user_id: UUID, other_user_id: UUID) -> None:
    mine = await _insert_note(user_id, "mine")
    theirs = await _insert_note(other_user_id, "theirs")

    listed = (await client.get("/api/notes", headers=auth_headers(user_id))).json()
    assert [n["id"] for n in listed] == [str(mine)]

    assert (await client.get(f"/api/notes/{mine}", headers=auth_headers(user_id))).status_code == 200
    assert (await client.get(f"/api/notes/{theirs}", headers=auth_headers(user_id))).status_code == 404
    assert (await client.delete(f"/api/notes/{theirs}", headers=auth_headers(user_id))).status_code == 404


async def test_rls_blocks_writing_as_someone_else(user_id: UUID, other_user_id: UUID) -> None:
    import psycopg

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with db.user_conn(user_id) as conn:
            await conn.execute(
                "insert into notes (user_id, title, summary, body) values (%s, 't', 's', 'b')", [other_user_id]
            )


async def test_hybrid_search_only_sees_own_chunks(user_id: UUID, other_user_id: UUID) -> None:
    mine = await _insert_note(user_id, "alpha")
    await _insert_note(other_user_id, "beta")
    async with db.user_conn(user_id) as conn:
        rows = await db.fetch_all(
            conn, "select note_id, score from match_note_chunks(%s::vector, %s, 10)", [VECTOR, "sleep"]
        )
    assert {row["note_id"] for row in rows} == {mine}
    assert all(row["score"] > 0 for row in rows)
