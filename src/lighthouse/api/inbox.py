"""Drop things in, and watch what happens to them.

Dropping only records the item and returns: the worker (lighthouse.worker) picks it up from the
`inbox_items` table and turns it into a note. The web app polls GET /inbox to follow the status.
"""

import re
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from lighthouse import db
from lighthouse.auth import CurrentUser
from lighthouse.schemas import DropRequest, InboxItem, InboxKind

router = APIRouter(tags=["inbox"])

_COLUMNS = "id, kind, content, status, error, note_id, created_at, updated_at"
# The list shows a preview only: a pasted item can be 200k characters, and the page polls.
PREVIEW_CHARS = 500
_LIST_COLUMNS = _COLUMNS.replace("content", f"left(content, {PREVIEW_CHARS}) as content")
# One URL and nothing else: no whitespace anywhere, and something after the scheme.
_SINGLE_URL = re.compile(r"https?://[^\s/]\S*", re.IGNORECASE)


def detect_kind(content: str) -> InboxKind:
    """`url` if the (already trimmed) content is a single http(s) URL, else `text`.

    A URL inside a sentence, or two URLs, stay text: the user pasted a note, not a page to fetch.
    """
    return "url" if _SINGLE_URL.fullmatch(content) else "text"


@router.post("/drop", status_code=status.HTTP_202_ACCEPTED)
async def drop(request: DropRequest, user_id: CurrentUser) -> InboxItem:
    # Postgres text cannot hold NUL characters.
    content = request.content.replace("\x00", "").strip()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "content is empty")
    async with db.user_conn(user_id) as conn:
        # user_id is not passed: the column defaults to auth.uid(), the caller.
        row = await db.fetch_one(
            conn,
            f"insert into inbox_items (kind, content) values (%s, %s) returning {_COLUMNS}",
            [detect_kind(content), content],
        )
    return InboxItem.model_validate(row)


@router.get("/inbox")
async def list_inbox(user_id: CurrentUser, limit: int = Query(default=50, ge=1, le=200)) -> list[InboxItem]:
    # No user_id filter needed: row level security already restricts rows to this user.
    async with db.user_conn(user_id) as conn:
        rows = await db.fetch_all(
            conn, f"select {_LIST_COLUMNS} from inbox_items order by created_at desc limit %s", [limit]
        )
    return [InboxItem.model_validate(row) for row in rows]


@router.post("/inbox/{item_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(item_id: UUID, user_id: CurrentUser) -> InboxItem:
    async with db.user_conn(user_id) as conn:
        # Back to the start of the queue's life cycle, with a fresh set of attempts. The status
        # check is part of the UPDATE, so two retry clicks cannot both succeed.
        row = await db.fetch_one(
            conn,
            "update inbox_items set status = 'pending', error = null, attempts = 0, updated_at = now() "
            f"where id = %s and status = 'failed' returning {_COLUMNS}",
            [item_id],
        )
        # Nothing updated: either the item is not failed, or it is not there (for this user).
        exists = row is not None or await db.fetch_one(conn, "select 1 from inbox_items where id = %s", [item_id])
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "inbox item not found")
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "only failed items can be retried")
    return InboxItem.model_validate(row)
