"""Conversation threads and their history.

A thread is two things: a row in `public.threads` (title, timestamps, owner) and the messages,
which live in the agent's checkpoints under the row's id. Row level security on the row decides
who may see a thread; the checkpoints are only ever reached through a row the caller owns.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from lighthouse import db
from lighthouse.agent import graph
from lighthouse.agent.transcript import to_chat_messages
from lighthouse.auth import CurrentUser
from lighthouse.schemas import ChatMessage, Thread

router = APIRouter(tags=["threads"])


@router.get("/threads")
async def list_threads(user_id: CurrentUser) -> list[Thread]:
    async with db.user_conn(user_id) as conn:
        rows = await db.fetch_all(
            conn, "select id, title, created_at, updated_at from threads order by updated_at desc, created_at desc"
        )
    return [Thread.model_validate(row) for row in rows]


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: UUID, user_id: CurrentUser) -> list[ChatMessage]:
    async with db.user_conn(user_id) as conn:
        row = await db.fetch_one(conn, "select id from threads where id = %s", [thread_id])
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread not found")
    # The latest checkpoint holds the whole message list; no separate messages table is needed.
    state = await graph.agent().aget_state({"configurable": {"thread_id": str(thread_id)}})
    return to_chat_messages(state.values.get("messages", []))


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(thread_id: UUID, user_id: CurrentUser) -> Response:
    async with db.user_conn(user_id) as conn:
        row = await db.fetch_one(conn, "delete from threads where id = %s returning id", [thread_id])
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "thread not found")
        # Still inside the transaction: if removing the checkpoints fails, the row comes back
        # and the delete can be retried, instead of leaving messages nobody can reach.
        await graph.checkpointer().adelete_thread(str(thread_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
