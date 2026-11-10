"""Reading the notes library on behalf of the chat agent.

Design rule: the agent reads only the *distilled* fields of a note, never
`notes.body` or the text of a source chunk. Source text is whatever a web page said, so it is
untrusted; the distilled fields were written by the distill step, a model call with no tools.
Source chunks still take part in the search, because they make a note findable by details the
summary left out, but a hit on one is answered with the note it belongs to.

Every query here runs on a `db.user_conn` connection, so row level security limits it to the
caller's own notes.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from lighthouse import db
from lighthouse.llm import embed_texts

# The only columns the agent may read. `body` is deliberately not in this list.
_DISTILLED_COLUMNS = "n.id, n.title, n.summary, n.key_points, n.tags, n.source_url, n.source_title, n.created_at"

# One note usually matches with several chunks, so ask for more chunks than notes wanted.
_CHUNKS_PER_NOTE = 4

_SHORT_ID = re.compile(r"[0-9a-f]{8}")


@dataclass(frozen=True)
class DistilledNote:
    """A note as the agent sees it."""

    id: UUID
    title: str
    summary: str
    key_points: list[str]
    tags: list[str]
    source_url: str | None
    source_title: str | None
    created_at: datetime

    @property
    def short_id(self) -> str:
        """First 8 hex characters of the id: what the answer cites as `[note:xxxxxxxx]`."""
        return self.id.hex[:8]


def _to_note(row: db.DictRow) -> DistilledNote:
    return DistilledNote(**{name: row[name] for name in DistilledNote.__dataclass_fields__})


async def search_notes(conn: db.Conn, query: str, limit: int = 5) -> list[DistilledNote]:
    """The notes that best match `query`, best first.

    `match_note_chunks` (see the migration) ranks chunks by vector similarity and by keyword
    match and fuses the two rankings. Here the chunk hits are collapsed to notes: a note scores
    as its best chunk, and only its distilled fields are returned.
    """
    [embedding] = await embed_texts([query], input_type="query")
    rows = await db.fetch_all(
        conn,
        f"""
        with hits as (
            select note_id, max(score) as score
            from match_note_chunks(%s::vector, %s, %s)
            group by note_id
        )
        select {_DISTILLED_COLUMNS}
        from hits h
        join notes n on n.id = h.note_id
        order by h.score desc, n.created_at desc
        limit %s
        """,
        [db.to_vector(embedding), query, limit * _CHUNKS_PER_NOTE, limit],
    )
    return [_to_note(row) for row in rows]


async def get_note(conn: db.Conn, note_id: str) -> DistilledNote | None:
    """One note by its full id or by the 8-character short id used in citations."""
    note_id = note_id.strip().lower()
    if _SHORT_ID.fullmatch(note_id):
        # Two of one user's notes sharing a prefix is a 1 in 4 billion event; take the newest.
        where, param = "n.id::text like %s", note_id + "%"
    else:
        try:
            where, param = "n.id = %s", UUID(note_id)
        except ValueError:
            return None
    row = await db.fetch_one(
        conn,
        f"select {_DISTILLED_COLUMNS} from notes n where {where} order by n.created_at desc limit 1",
        [param],
    )
    return _to_note(row) if row else None
