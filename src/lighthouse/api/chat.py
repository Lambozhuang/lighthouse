"""Chat with the agent over server-sent events. The event stream is specified in docs/API.md."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage
from sse_starlette import EventSourceResponse, ServerSentEvent

from lighthouse import db
from lighthouse.agent import graph
from lighthouse.agent.transcript import PARAGRAPH_BREAK, to_chat_messages
from lighthouse.auth import CurrentUser
from lighthouse.llm import trace_config
from lighthouse.schemas import ChatRequest, Thread

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

TITLE_MAX_CHARS = 60


def _title_from(message: str) -> str:
    """A thread is titled with its first message, on one line and cut to a readable length."""
    title = " ".join(message.split())
    return title if len(title) <= TITLE_MAX_CHARS else title[: TITLE_MAX_CHARS - 1].rstrip() + "…"


async def _open_thread(user_id: UUID, request: ChatRequest) -> Thread:
    """Create the thread, or check that an existing one is the caller's and mark it as used."""
    columns = "id, title, created_at, updated_at"
    async with db.user_conn(user_id) as conn:
        if request.thread_id is None:
            # user_id defaults to auth.uid(), the caller.
            row = await db.fetch_one(
                conn, f"insert into threads (title) values (%s) returning {columns}", [_title_from(request.message)]
            )
        else:
            # Row level security hides other users' threads, so "not mine" and "does not exist"
            # look the same here: no row.
            row = await db.fetch_one(
                conn, f"update threads set updated_at = now() where id = %s returning {columns}", [request.thread_id]
            )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread not found")
    return Thread.model_validate(row)


def _event(name: str, data: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(event=name, data=json.dumps(data, ensure_ascii=False))


async def _turn_events(user_id: UUID, thread: Thread, message: str) -> AsyncIterator[ServerSentEvent]:
    """Run one turn of the agent and translate what the graph does into the API's events."""
    yield _event("thread", {"thread_id": str(thread.id), "title": thread.title})

    # One Langfuse trace per turn, grouped into a session per thread.
    config = trace_config("chat", user_id=str(user_id), session_id=str(thread.id))
    # thread_id selects the checkpoint; user_id is what the tools read notes as (agent/tools.py).
    config["configurable"] = {"thread_id": str(thread.id), "user_id": str(user_id)}
    agent = graph.agent()

    said_something = False
    break_before_next_text = False
    try:
        await graph.close_interrupted_turn(agent, config)
        # Two stream modes at once; each item says which mode it is from.
        # "messages": pieces of a model reply as they are generated, as (chunk, metadata).
        # "updates":  {node name: what the node returned}, once per finished node.
        stream = agent.astream({"messages": [HumanMessage(message)]}, config, stream_mode=["messages", "updates"])
        async for mode, item in cast(AsyncIterator[tuple[str, Any]], stream):
            if mode == "messages":
                chunk, _metadata = item
                # Tool results also pass through this mode; only the model's reply is answer text.
                # `.text` holds text blocks only, so thinking and the JSON fragments of a tool
                # call being written never become tokens.
                #
                # How smoothly tokens arrive is up to the provider. Measured in November 2026
                # with claude-sonnet-5-5 (also with Anthropic's own SDK, so it is not this code
                # or LiteLLM): a reply that follows a tool result is delivered in one burst when
                # it is complete, while a reply to a plain user message streams piece by piece.
                if isinstance(chunk, AIMessage) and chunk.text:
                    text = str(chunk.text)
                    if break_before_next_text:
                        text, break_before_next_text = PARAGRAPH_BREAK + text, False
                    said_something = True
                    yield _event("token", {"text": text})
            else:
                for update in item.values():
                    for new_message in update["messages"]:
                        if isinstance(new_message, AIMessage):
                            for call in new_message.tool_calls:
                                yield _event("tool", {"name": call["name"], "input": call["args"]})
                        else:
                            # A tool result. If the model wrote text before calling the tool,
                            # what it writes next is a new paragraph (the history endpoint
                            # joins the two the same way).
                            break_before_next_text = said_something
        # The turn is saved now. Take the answer's sources from the saved thread with the same
        # code the history endpoint uses, so both always agree.
        state = await agent.aget_state(config)
        last = to_chat_messages(state.values["messages"])[-1]
        sources = last.sources if last.role == "assistant" else []
        yield _event("sources", {"sources": [source.model_dump(mode="json") for source in sources]})
        yield _event("done", {})
    except Exception:
        # The response has already started, so the status code cannot change any more. Report the
        # failure in-band; the details go to the log, not to the browser.
        logger.exception("chat turn failed (thread %s)", thread.id)
        yield _event("error", {"message": "The assistant could not finish this answer. Please try again."})


@router.post("/chat")
async def chat(request: ChatRequest, user_id: CurrentUser) -> EventSourceResponse:
    # Done before the stream starts, so a thread that is not the caller's is a plain 404.
    thread = await _open_thread(user_id, request)
    return EventSourceResponse(_turn_events(user_id, thread, request.message))
