"""The pipeline end to end, and the worker around it: claiming, failing, retrying, recovering.

The model and the embedding API are replaced by fakes, and web pages come from a mock transport,
so these tests need only the database.
"""

import asyncio
import functools
import os
import signal
import sys
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio

from lighthouse import db, llm, worker
from lighthouse.config import get_settings
from lighthouse.ingest import distill, fetch, pipeline
from lighthouse.ingest.chunk import chunk_text
from lighthouse.ingest.distill import Distilled
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOTE = Distilled(
    title="Why sleep matters",
    summary="Sleep consolidates memory. People who sleep seven hours remember more.",
    key_points=["Seven to eight hours is the useful range.", "Naps do not replace night sleep."],
    tags=["sleep", "memory"],
)
LONG_TEXT = "\n\n".join(f"Paragraph {i}. " + "Sleep helps the brain consolidate memories. " * 12 for i in range(6))


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def empty_queue() -> AsyncIterator[None]:
    """The worker takes the oldest pending item of any user, so start each test with none.
    Clean up afterwards too, so no other test file finds leftovers."""
    async with db.service_conn() as conn:
        await conn.execute("delete from inbox_items")
    yield
    async with db.service_conn() as conn:
        await conn.execute("delete from inbox_items")


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Replace the two paid calls. Returns what they were called with."""
    calls: dict[str, list[Any]] = {"distill": [], "embed": []}

    async def fake_distill(text: str, *, user_id: UUID) -> Distilled:
        calls["distill"].append(text)
        return NOTE

    async def fake_embed(texts: list[str], **_: Any) -> list[list[float]]:
        calls["embed"].append(texts)
        return [[0.01 * (i + 1)] * 1536 for i in range(len(texts))]

    monkeypatch.setattr(distill, "distill", fake_distill)
    monkeypatch.setattr(llm, "embed_texts", fake_embed)
    monkeypatch.setattr(worker, "RETRY_DELAY_SECONDS", 0)  # tests do not wait between attempts
    return calls


async def add_item(user_id: UUID, content: str, kind: str = "text", **columns: Any) -> UUID:
    values = {"user_id": user_id, "kind": kind, "content": content, **columns}
    async with db.service_conn() as conn:
        row = await db.fetch_one(
            conn,
            f"insert into inbox_items ({', '.join(values)}) values ({', '.join(['%s'] * len(values))}) returning id",
            list(values.values()),
        )
    assert row is not None
    return row["id"]


async def get_item(item_id: UUID) -> dict[str, Any]:
    async with db.service_conn() as conn:
        row = await db.fetch_one(conn, "select * from inbox_items where id = %s", [item_id])
    assert row is not None
    return row


async def count_notes(user_id: UUID) -> int:
    async with db.service_conn() as conn:
        row = await db.fetch_one(conn, "select count(*) as n from notes where user_id = %s", [user_id])
    assert row is not None
    return row["n"]


# --- the pipeline ---


async def test_text_item_becomes_a_note_with_both_kinds_of_chunks(
    client: httpx.AsyncClient, user_id: UUID, other_user_id: UUID, fakes: dict[str, list[Any]]
) -> None:
    item_id = await add_item(user_id, LONG_TEXT)

    assert await worker.run_once() is True

    item = await get_item(item_id)
    assert (item["status"], item["error"], item["attempts"]) == ("done", None, 1)
    assert item["note_id"] is not None

    # The note, read back through the API as its owner.
    note = (await client.get(f"/api/notes/{item['note_id']}", headers=auth_headers(user_id))).json()
    assert note["title"] == NOTE.title and note["summary"] == NOTE.summary
    assert note["key_points"] == NOTE.key_points and note["tags"] == NOTE.tags
    assert note["body"] == LONG_TEXT
    assert note["source_url"] is None and note["source_title"] is None
    stranger = await client.get(f"/api/notes/{item['note_id']}", headers=auth_headers(other_user_id))
    assert stranger.status_code == 404

    async with db.service_conn() as conn:
        chunks = await db.fetch_all(
            conn,
            "select kind::text, chunk_index, content, user_id, vector_dims(embedding) as dims "
            "from note_chunks where note_id = %s order by kind, chunk_index",
            [item["note_id"]],
        )
    assert all(chunk["user_id"] == user_id and chunk["dims"] == 1536 for chunk in chunks)

    distilled = [chunk for chunk in chunks if chunk["kind"] == "distilled"]
    assert [chunk["chunk_index"] for chunk in distilled] == [0], "a normal note is one distilled chunk"
    for part in (NOTE.title, NOTE.summary, *NOTE.key_points):
        assert part in distilled[0]["content"]

    source = [chunk for chunk in chunks if chunk["kind"] == "source"]
    assert len(source) > 1
    assert [chunk["content"] for chunk in source] == chunk_text(LONG_TEXT)
    assert [chunk["chunk_index"] for chunk in source] == list(range(len(source)))

    # One distill call on the text, one embedding call for all chunks together.
    assert fakes["distill"] == [LONG_TEXT]
    assert [len(texts) for texts in fakes["embed"]] == [len(chunks)]


async def test_url_item_is_fetched_first(user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    article = (
        "<html><head><title>Why sleep matters</title></head><body><article><h1>Why sleep matters</h1><p>"
        + "Sleep helps the brain consolidate memories. " * 15
        + "</p></article></body></html>"
    )

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s/abc":
            return httpx.Response(301, headers={"location": "/posts/sleep"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=article.encode())

    async def resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(fetch, "resolve", resolve)
    monkeypatch.setattr(fetch, "fetch_page", functools.partial(fetch.fetch_page, transport=httpx.MockTransport(site)))
    item_id = await add_item(user_id, "https://blog.example/s/abc", kind="url")

    await worker.run_once()

    item = await get_item(item_id)
    assert item["status"] == "done", item["error"]
    async with db.service_conn() as conn:
        note = await db.fetch_one(conn, "select * from notes where id = %s", [item["note_id"]])
    assert note is not None
    assert note["user_id"] == user_id
    assert note["source_url"] == "https://blog.example/posts/sleep"  # after the redirect
    assert note["source_title"] == "Why sleep matters"
    assert "Sleep helps the brain consolidate memories." in note["body"]


# --- failures ---


async def test_permanent_failure_is_not_retried(user_id: UUID, fakes: dict[str, list[Any]]) -> None:
    # The real fetch code runs here: the SSRF guard refuses before any connection is made.
    item_id = await add_item(user_id, "http://192.168.1.1/admin", kind="url")

    await worker.run_once()

    item = await get_item(item_id)
    assert (item["status"], item["attempts"], item["note_id"]) == ("failed", 1, None)
    assert "private or local network" in item["error"]
    assert fakes["distill"] == [] and await count_notes(user_id) == 0
    assert await worker.run_once() is False, "a failed item is not picked up again"


async def test_transient_failure_is_retried_up_to_the_limit(user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken_distill(text: str, *, user_id: UUID) -> Distilled:
        raise RuntimeError("model API is down, with internal details the user should not see")

    monkeypatch.setattr(distill, "distill", broken_distill)
    item_id = await add_item(user_id, "some text")
    max_attempts = get_settings().worker_max_attempts

    for attempt in range(1, max_attempts):
        await worker.run_once()
        item = await get_item(item_id)
        assert (item["status"], item["attempts"], item["error"]) == ("pending", attempt, None)

    await worker.run_once()
    item = await get_item(item_id)
    assert (item["status"], item["attempts"]) == ("failed", max_attempts)
    assert item["error"] == "Unexpected error (RuntimeError); retry later"
    assert await count_notes(user_id) == 0


async def test_transient_failure_then_success(user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    real_fake = distill.distill
    outcomes = iter([TimeoutError(), None])

    async def flaky_distill(text: str, *, user_id: UUID) -> Distilled:
        if error := next(outcomes):
            raise error
        return await real_fake(text, user_id=user_id)

    monkeypatch.setattr(distill, "distill", flaky_distill)
    item_id = await add_item(user_id, "some text")

    await worker.run_once()
    await worker.run_once()

    item = await get_item(item_id)
    assert (item["status"], item["attempts"]) == ("done", 2)
    assert await count_notes(user_id) == 1


async def test_retry_waits_between_attempts(user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "RETRY_DELAY_SECONDS", 30)
    waiting = await add_item(user_id, "failed a moment ago", attempts=1)
    async with db.service_conn() as conn:
        assert await worker.claim(conn) is None, "one failed attempt: not due for 30 seconds"
        await conn.execute("update inbox_items set updated_at = now() - interval '31 seconds'")
        claimed = await worker.claim(conn)
    assert claimed is not None and claimed.id == waiting


async def test_failed_write_leaves_nothing_behind(user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    async def wrong_size_embed(texts: list[str], **_: Any) -> list[list[float]]:
        return [[0.1] * 3 for _ in texts]  # the column is vector(1536): the chunk insert fails

    monkeypatch.setattr(llm, "embed_texts", wrong_size_embed)
    item_id = await add_item(user_id, "some text")

    await worker.run_once()

    # The note row was inserted before the chunks failed; the transaction took it back.
    assert await count_notes(user_id) == 0
    assert (await get_item(item_id))["note_id"] is None


async def test_result_is_dropped_if_the_item_was_finished_elsewhere(user_id: UUID) -> None:
    # After a crash recovery two workers can end up with the same item; only the first may write.
    item_id = await add_item(user_id, "some text", status="done", attempts=1)
    item = pipeline.Item(id=item_id, user_id=user_id, kind="text", content="some text", attempts=1)

    assert await pipeline.process(item) is None
    assert await count_notes(user_id) == 0


# --- the queue ---


async def test_items_are_claimed_oldest_first(user_id: UUID) -> None:
    first = await add_item(user_id, "first")
    second = await add_item(user_id, "second")
    async with db.service_conn() as conn:
        claimed = [await worker.claim(conn), await worker.claim(conn), await worker.claim(conn)]
    assert [item.id if item else None for item in claimed] == [first, second, None]
    assert (await get_item(first))["status"] == "processing"


async def test_two_workers_never_claim_the_same_item(user_id: UUID) -> None:
    first = await add_item(user_id, "first")
    second = await add_item(user_id, "second")

    # Two workers in the middle of claiming at the same moment: both transactions are open.
    # Worker A holds a row lock on the first item; worker B must skip it, not wait and not take it.
    async with db.service_conn() as worker_a, db.service_conn() as worker_b:
        await worker_b.execute("set local lock_timeout = '2s'")  # fail instead of hanging if B waits
        item_a = await worker.claim(worker_a)
        item_b = await worker.claim(worker_b)
        nothing_left = await worker.claim(worker_b)
    assert item_a is not None and item_b is not None
    assert (item_a.id, item_b.id) == (first, second)
    assert nothing_left is None


async def test_concurrent_workers_process_each_item_once(user_id: UUID, fakes: dict[str, list[Any]]) -> None:
    item_ids = [await add_item(user_id, f"note number {i}") for i in range(6)]

    results = await asyncio.gather(*(worker.run_once() for _ in range(10)))

    assert sorted(results) == [False] * 4 + [True] * 6
    assert sorted(fakes["distill"]) == sorted(f"note number {i}" for i in range(6))
    assert await count_notes(user_id) == 6
    for item_id in item_ids:
        item = await get_item(item_id)
        assert (item["status"], item["attempts"]) == ("done", 1)


async def test_recover_stuck_items_on_startup(user_id: UUID) -> None:
    max_attempts = get_settings().worker_max_attempts
    interrupted = await add_item(user_id, "worker died once", status="processing", attempts=1)
    poison = await add_item(user_id, "kills the worker every time", status="processing", attempts=max_attempts)
    untouched = await add_item(user_id, "already failed", status="failed", error="earlier", attempts=1)

    await worker.recover_stuck()

    assert (await get_item(interrupted))["status"] == "pending"
    item = await get_item(poison)
    assert (item["status"], item["error"]) == ("failed", "Processing was interrupted too many times")
    assert (await get_item(untouched))["error"] == "earlier"


# --- the loop ---


async def test_run_works_through_the_queue_and_stops_when_asked(user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    item_ids = [await add_item(user_id, f"note {i}") for i in range(3)]
    queue_empty = asyncio.Event()
    real_run_once = worker.run_once

    async def run_once() -> bool:
        worked = await real_run_once()
        if not worked:
            queue_empty.set()
        return worked

    monkeypatch.setattr(worker, "run_once", run_once)
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))

    await asyncio.wait_for(queue_empty.wait(), timeout=10)
    assert [(await get_item(item_id))["status"] for item_id in item_ids] == ["done"] * 3
    # The worker now sleeps until its next poll. Asked to stop, it must return well before that.
    assert get_settings().worker_poll_seconds >= 1
    stop.set()
    await asyncio.wait_for(task, timeout=0.5)


async def test_worker_process_exits_cleanly_on_sigterm(database_url: str) -> None:
    """`python -m lighthouse.worker` for real, with an empty queue, so it calls no model."""
    env = {**os.environ, "DATABASE_URL": database_url, "ANTHROPIC_API_KEY": "", "OPENROUTER_API_KEY": ""}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "lighthouse.worker", env=env, stderr=asyncio.subprocess.PIPE
    )
    assert process.stderr is not None
    try:
        async with asyncio.timeout(20):
            while b"worker started" not in await process.stderr.readline():
                pass
            process.send_signal(signal.SIGTERM)
            log = await process.stderr.read()
            assert await process.wait() == 0
        assert b"worker stopped" in log
    finally:
        if process.returncode is None:
            process.kill()


async def test_run_recovers_an_item_left_processing_by_a_loop_error(
    user_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = await add_item(user_id, "left behind when the database went away", status="processing", attempts=1)
    stop = asyncio.Event()
    calls = 0

    async def run_once() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            # Mark it stuck only now, after the startup recovery has already run.
            async with db.service_conn() as conn:
                await conn.execute("update inbox_items set status = 'processing' where id = %s", [stuck])
            raise RuntimeError("database restarted")
        stop.set()
        return False

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(get_settings(), "worker_poll_seconds", 0.01)
    await asyncio.wait_for(worker.run(stop), timeout=5)

    assert (await get_item(stuck))["status"] == "pending"
