"""From one inbox item to one note: fetch (if it is a URL) → distill → chunk → embed → write."""

import logging
from dataclasses import dataclass
from uuid import UUID

from lighthouse import db, llm
from lighthouse.ingest import distill, fetch
from lighthouse.ingest.chunk import chunk_text
from lighthouse.schemas import InboxKind

log = logging.getLogger(__name__)

# Same ceiling as pasted text (DropRequest.content), so one huge web page cannot produce
# thousands of chunks to embed.
MAX_BODY_CHARS = 200_000
# Title, summary and key points together are usually 1000 to 2000 characters. They work best as
# one retrieval unit, so they are split only when unusually long.
DISTILLED_CHUNK_SIZE = 3000


@dataclass(frozen=True)
class Item:
    """The part of an `inbox_items` row the worker passes around."""

    id: UUID
    user_id: UUID
    kind: InboxKind
    content: str
    attempts: int


async def process(item: Item) -> UUID | None:
    """Create the note for `item` and mark the item done. Returns the note id.

    Raises on any failure, with nothing written: the caller (the worker) decides whether to
    retry. The slow steps (network, model calls) run before the database transaction opens.
    """
    if item.kind == "url":
        page = await fetch.fetch_page(item.content)
        source_url, source_title, body = page.url, page.title, page.text
    else:
        source_url, source_title, body = None, None, item.content
    # Postgres text cannot hold NUL characters.
    body = body.replace("\x00", "")[:MAX_BODY_CHARS]

    note = await distill.distill(body, user_id=item.user_id)

    chunks = [("distilled", i, text) for i, text in enumerate(chunk_text(distilled_text(note), DISTILLED_CHUNK_SIZE))]
    chunks += [("source", i, text) for i, text in enumerate(chunk_text(body))]
    vectors = await llm.embed_texts([text for _, _, text in chunks])

    # One transaction: either the note, all its chunks and the `done` status exist, or none do.
    # service_conn bypasses row level security, so user_id is always set from the inbox row.
    async with db.service_conn() as conn:
        # Lock the inbox row first. If it is gone or no longer ours (after a crash recovery
        # another worker may have finished it), write nothing rather than a duplicate note.
        mine = await db.fetch_one(
            conn, "select id from inbox_items where id = %s and status = 'processing' for update", [item.id]
        )
        if mine is None:
            log.warning("item %s is no longer processing; dropping the result", item.id)
            return None
        row = await db.fetch_one(
            conn,
            "insert into notes (user_id, title, summary, key_points, tags, source_url, source_title, body) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
            [item.user_id, note.title, note.summary, note.key_points, note.tags, source_url, source_title, body],
        )
        assert row is not None
        note_id: UUID = row["id"]
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into note_chunks (note_id, user_id, kind, chunk_index, content, embedding) "
                "values (%s, %s, %s, %s, %s, %s::vector)",
                [
                    (note_id, item.user_id, kind, index, text, db.to_vector(vector))
                    for (kind, index, text), vector in zip(chunks, vectors, strict=True)
                ],
            )
        await conn.execute(
            "update inbox_items set status = 'done', note_id = %s, error = null, updated_at = now() where id = %s",
            [note_id, item.id],
        )
    return note_id


def distilled_text(note: distill.Distilled) -> str:
    """What the 'distilled' chunk says: the note as the chat agent's search will see it."""
    points = "\n".join(f"- {point}" for point in note.key_points)
    return f"{note.title}\n\n{note.summary}\n\n{points}".strip()
