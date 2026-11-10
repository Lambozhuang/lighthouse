"""Stand-ins for the model and the embedding service, and a way to put notes in the database.

Tests never call a real model: embeddings are computed locally from the words of a text, and
the chat model is a script of prepared replies.
"""

import json
import re
import zlib
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from lighthouse import db

DIMENSIONS = 1536
# Text that must never reach the browser or the model; tests search their outputs for it.
THINKING_SENTINEL = "PRIVATE-REASONING"
BODY_SENTINEL = "RAW-BODY-TEXT"
SOURCE_CHUNK_SENTINEL = "RAW-SOURCE-CHUNK"


def fake_embedding(text: str) -> list[float]:
    """Bag of words: each word switches on one dimension, so texts sharing words are close."""
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"\w+", text.lower()):
        vector[zlib.crc32(word.encode()) % DIMENSIONS] = 1.0
    if not any(vector):
        vector[0] = 1.0  # cosine distance is undefined for the zero vector
    return vector


async def fake_embed_texts(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    return [fake_embedding(text) for text in texts]


async def seed_note(
    user_id: UUID,
    title: str,
    summary: str,
    *,
    key_points: Sequence[str] = (),
    tags: Sequence[str] = (),
    source_url: str | None = None,
    source_chunks: Sequence[str] = (),
) -> UUID:
    """Insert a note the way the ingest pipeline leaves one: the row, one 'distilled' chunk and
    any number of 'source' chunks. The body and the source chunks carry sentinel text."""
    body = f"{BODY_SENTINEL} " + " ".join(source_chunks)
    distilled = "\n".join([title, summary, *key_points])
    chunks = [("distilled", 0, distilled)]
    chunks += [("source", index, f"{SOURCE_CHUNK_SENTINEL} {text}") for index, text in enumerate(source_chunks)]
    async with db.service_conn() as conn:
        note = await db.fetch_one(
            conn,
            "insert into notes (user_id, title, summary, key_points, tags, source_url, body) "
            "values (%s, %s, %s, %s, %s, %s, %s) returning id",
            [user_id, title, summary, list(key_points), list(tags), source_url, body],
        )
        assert note is not None
        for kind, index, content in chunks:
            await conn.execute(
                "insert into note_chunks (note_id, user_id, kind, chunk_index, content, embedding) "
                "values (%s, %s, %s, %s, %s, %s::vector)",
                [note["id"], user_id, kind, index, content, db.to_vector(fake_embedding(content))],
            )
    return note["id"]


class ScriptedChatModel(BaseChatModel):
    """A chat model that plays back prepared replies, one per call, and records what it was sent.

    A reply is streamed the way a real one is: first some thinking, then the text in pieces,
    then each tool call with its JSON arguments split in two.
    """

    replies: list[AIMessage]
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _next_reply(self, messages: list[BaseMessage]) -> AIMessage:
        self.seen.append(list(messages))
        if not self.replies:
            raise RuntimeError("the script has no reply left")
        return self.replies.pop(0)

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any):
        return ChatResult(generations=[ChatGeneration(message=self._next_reply(messages))])

    async def _astream(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        reply = self._next_reply(messages)

        def chunk(**fields: Any) -> ChatGenerationChunk:
            return ChatGenerationChunk(message=AIMessageChunk(**{"content": "", **fields}))

        yield chunk(additional_kwargs={"reasoning_content": THINKING_SENTINEL})
        for piece in re.findall(r"\S+\s*", str(reply.text)):
            yield chunk(content=piece)
        for index, call in enumerate(reply.tool_calls):
            arguments = json.dumps(call["args"])
            half = len(arguments) // 2
            yield chunk(
                tool_call_chunks=[{"name": call["name"], "args": arguments[:half], "id": call["id"], "index": index}]
            )
            yield chunk(tool_call_chunks=[{"name": None, "args": arguments[half:], "id": None, "index": index}])


def sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse a server-sent event stream into (event name, data) pairs. Keep-alive comments are skipped."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in re.split(r"\r?\n\r?\n", body):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events
