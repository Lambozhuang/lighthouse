"""Retrieval: chunks are searched, notes are returned, and only the caller's, without `body`."""

from uuid import UUID

import pytest

from lighthouse import db, retrieval
from lighthouse.agent.tools import format_note
from tests.helpers import BODY_SENTINEL, SOURCE_CHUNK_SENTINEL, fake_embed_texts, seed_note

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieval, "embed_texts", fake_embed_texts)


async def test_search_collapses_chunks_to_notes(user_id: UUID) -> None:
    # Three chunks of one note match the query; the note must come back once, and first.
    espresso = await seed_note(
        user_id,
        "Espresso after lunch",
        "Decided to stop drinking espresso after 14:00.",
        key_points=["Espresso late in the day delays sleep"],
        source_chunks=["espresso has a half-life of five hours", "an espresso at dinner still acts at midnight"],
    )
    garden = await seed_note(user_id, "Tomato garden", "Tomatoes want full sun and espresso grounds as mulch.")
    await seed_note(user_id, "Tax return", "The deadline is the end of May.")

    async with db.user_conn(user_id) as conn:
        notes = await retrieval.search_notes(conn, "espresso", limit=2)

    assert [note.id for note in notes] == [espresso, garden]
    assert notes[0].title == "Espresso after lunch"
    assert notes[0].key_points == ["Espresso late in the day delays sleep"]


async def test_source_chunks_make_a_note_findable_but_are_not_returned(user_id: UUID) -> None:
    # "chamomile" appears only in a source chunk, not in the distilled fields.
    note_id = await seed_note(
        user_id, "Evening routine", "Wind down without screens.", source_chunks=["a cup of chamomile helps"]
    )

    async with db.user_conn(user_id) as conn:
        notes = await retrieval.search_notes(conn, "chamomile")

    assert notes[0].id == note_id
    shown_to_model = format_note(notes[0])
    assert "Wind down without screens." in shown_to_model
    for raw in (BODY_SENTINEL, SOURCE_CHUNK_SENTINEL, "chamomile"):
        assert raw not in shown_to_model and raw not in repr(notes[0])


async def test_search_never_returns_another_users_notes(user_id: UUID, other_user_id: UUID) -> None:
    mine = await seed_note(user_id, "Kefir recipe", "Ferment kefir for 24 hours.")
    theirs = await seed_note(other_user_id, "Kefir recipe", "Ferment kefir for 24 hours.")

    async with db.user_conn(user_id) as conn:
        found = await retrieval.search_notes(conn, "kefir recipe")
        assert [note.id for note in found] == [mine]
        assert await retrieval.get_note(conn, str(theirs)) is None
        assert await retrieval.get_note(conn, theirs.hex[:8]) is None


async def test_get_note_by_full_or_short_id(user_id: UUID) -> None:
    note_id = await seed_note(user_id, "Standing desk", "Alternate sitting and standing every hour.", tags=["health"])

    async with db.user_conn(user_id) as conn:
        by_full_id = await retrieval.get_note(conn, str(note_id))
        by_short_id = await retrieval.get_note(conn, note_id.hex[:8])
        assert await retrieval.get_note(conn, "not-an-id") is None
        assert await retrieval.get_note(conn, "00000000") is None

    assert by_full_id is not None and by_full_id == by_short_id
    assert by_full_id.short_id == note_id.hex[:8]
    assert by_full_id.tags == ["health"]
