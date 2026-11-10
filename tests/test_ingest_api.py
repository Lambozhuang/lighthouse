"""The inbox endpoints: drop, list, retry. Ownership is enforced by row level security."""

from uuid import UUID, uuid4

import httpx
import pytest

from lighthouse import db
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _drop(client: httpx.AsyncClient, user_id: UUID, content: str) -> dict:
    response = await client.post("/api/drop", json={"content": content}, headers=auth_headers(user_id))
    assert response.status_code == 202, response.text
    return response.json()


async def _set_status(item_id: str, status: str, error: str | None = None) -> None:
    """What the worker would do; the API itself never moves an item out of `pending`."""
    async with db.service_conn() as conn:
        await conn.execute(
            "update inbox_items set status = %s, error = %s, attempts = 3 where id = %s", [status, error, item_id]
        )


@pytest.mark.parametrize(
    ("content", "kind", "stored"),
    [
        ("https://example.com/article?id=1#top", "url", "https://example.com/article?id=1#top"),
        ("  http://example.com \n", "url", "http://example.com"),  # trimmed first
        ("HTTPS://EXAMPLE.COM/A", "url", "HTTPS://EXAMPLE.COM/A"),
        ("Read https://example.com later", "text", "Read https://example.com later"),
        ("https://a.example https://b.example", "text", "https://a.example https://b.example"),
        ("https://a.example\nand a comment", "text", "https://a.example\nand a comment"),
        ("example.com/article", "text", "example.com/article"),  # no scheme
        ("ftp://example.com/file", "text", "ftp://example.com/file"),
        ("https://", "text", "https://"),
        ("Sleep before eleven.", "text", "Sleep before eleven."),
    ],
)
async def test_drop_detects_url_or_text(
    client: httpx.AsyncClient, user_id: UUID, content: str, kind: str, stored: str
) -> None:
    item = await _drop(client, user_id, content)
    assert (item["kind"], item["content"]) == (kind, stored)


async def test_drop_returns_a_pending_item(client: httpx.AsyncClient, user_id: UUID) -> None:
    item = await _drop(client, user_id, "A thought worth keeping.")
    assert item["status"] == "pending"
    assert item["error"] is None and item["note_id"] is None
    assert set(item) == {"id", "kind", "content", "status", "error", "note_id", "created_at", "updated_at"}


async def test_drop_rejects_bad_requests(client: httpx.AsyncClient, user_id: UUID) -> None:
    assert (await client.post("/api/drop", json={"content": "no token"})).status_code == 401
    for content in ["", "   \n\t "]:
        response = await client.post("/api/drop", json={"content": content}, headers=auth_headers(user_id))
        assert response.status_code == 422


async def test_inbox_lists_own_items_newest_first(
    client: httpx.AsyncClient, user_id: UUID, other_user_id: UUID
) -> None:
    first = await _drop(client, user_id, "first")
    second = await _drop(client, user_id, "second")
    theirs = await _drop(client, other_user_id, "theirs")

    mine = (await client.get("/api/inbox", headers=auth_headers(user_id))).json()
    assert [item["id"] for item in mine] == [second["id"], first["id"]]

    limited = (await client.get("/api/inbox?limit=1", headers=auth_headers(user_id))).json()
    assert [item["id"] for item in limited] == [second["id"]]

    other = (await client.get("/api/inbox", headers=auth_headers(other_user_id))).json()
    assert [item["id"] for item in other] == [theirs["id"]]


async def test_retry_puts_a_failed_item_back_in_the_queue(client: httpx.AsyncClient, user_id: UUID) -> None:
    item = await _drop(client, user_id, "https://example.com/flaky")
    await _set_status(item["id"], "failed", "The page took too long to load")

    response = await client.post(f"/api/inbox/{item['id']}/retry", headers=auth_headers(user_id))
    assert response.status_code == 202
    retried = response.json()
    assert (retried["status"], retried["error"]) == ("pending", None)

    async with db.service_conn() as conn:
        row = await db.fetch_one(conn, "select attempts from inbox_items where id = %s", [item["id"]])
    assert row is not None and row["attempts"] == 0, "a manual retry gets a fresh set of attempts"


@pytest.mark.parametrize("status", ["pending", "processing", "done"])
async def test_retry_is_only_for_failed_items(client: httpx.AsyncClient, user_id: UUID, status: str) -> None:
    item = await _drop(client, user_id, "some text")
    await _set_status(item["id"], status)
    response = await client.post(f"/api/inbox/{item['id']}/retry", headers=auth_headers(user_id))
    assert response.status_code == 409


async def test_retry_someone_elses_item_is_not_found(
    client: httpx.AsyncClient, user_id: UUID, other_user_id: UUID
) -> None:
    theirs = await _drop(client, other_user_id, "private")
    await _set_status(theirs["id"], "failed", "boom")

    response = await client.post(f"/api/inbox/{theirs['id']}/retry", headers=auth_headers(user_id))
    assert response.status_code == 404
    # ...and it was not touched.
    listed = (await client.get("/api/inbox", headers=auth_headers(other_user_id))).json()
    assert listed[0]["status"] == "failed"

    unknown = await client.post(f"/api/inbox/{uuid4()}/retry", headers=auth_headers(user_id))
    assert unknown.status_code == 404


async def test_inbox_list_returns_a_preview_of_long_content(client: httpx.AsyncClient, user_id: UUID) -> None:
    long_text = "word " * 1000
    dropped = (await client.post("/api/drop", json={"content": long_text}, headers=auth_headers(user_id))).json()
    assert dropped["content"] == long_text.strip()
    listed = (await client.get("/api/inbox", headers=auth_headers(user_id))).json()
    assert len(next(item for item in listed if item["id"] == dropped["id"])["content"]) == 500
