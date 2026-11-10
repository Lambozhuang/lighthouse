"""Browse the notes library."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from lighthouse import db
from lighthouse.auth import CurrentUser
from lighthouse.schemas import Note, NoteSummary

router = APIRouter(tags=["notes"])


@router.get("/notes")
async def list_notes(
    user_id: CurrentUser,
    q: str | None = Query(default=None, description="Keyword filter on title and summary"),
    tag: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[NoteSummary]:
    # No user_id filter needed: row level security already restricts rows to this user.
    async with db.user_conn(user_id) as conn:
        rows = await db.fetch_all(
            conn,
            """
            select id, title, summary, tags, source_url, created_at
            from notes
            where (%(q)s::text is null or title ilike '%%' || %(q)s || '%%' or summary ilike '%%' || %(q)s || '%%')
              and (%(tag)s::text is null or %(tag)s = any (tags))
            order by created_at desc
            limit %(limit)s offset %(offset)s
            """,
            {"q": q, "tag": tag, "limit": limit, "offset": offset},  # pyright: ignore[reportArgumentType, reportCallIssue]
        )
    return [NoteSummary.model_validate(row) for row in rows]


@router.get("/notes/{note_id}")
async def get_note(note_id: UUID, user_id: CurrentUser) -> Note:
    async with db.user_conn(user_id) as conn:
        row = await db.fetch_one(
            conn,
            "select id, title, summary, key_points, tags, source_url, source_title, body, created_at "
            "from notes where id = %s",
            [note_id],
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    return Note.model_validate(row)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: UUID, user_id: CurrentUser) -> Response:
    async with db.user_conn(user_id) as conn:
        row = await db.fetch_one(conn, "delete from notes where id = %s returning id", [note_id])
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
