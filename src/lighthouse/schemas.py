"""Request and response models: the contract between the API and the web app.

docs/API.md describes the same shapes for the frontend, including the chat event stream.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

InboxKind = Literal["text", "url"]
InboxStatus = Literal["pending", "processing", "done", "failed"]


class DropRequest(BaseModel):
    # A URL on its own is fetched; anything else is filed as text.
    content: str = Field(min_length=1, max_length=200_000)


class InboxItem(BaseModel):
    id: UUID
    kind: InboxKind
    content: str
    status: InboxStatus
    error: str | None
    note_id: UUID | None
    created_at: datetime
    updated_at: datetime


class NoteSummary(BaseModel):
    id: UUID
    title: str
    summary: str
    tags: list[str]
    source_url: str | None
    created_at: datetime


class Note(NoteSummary):
    key_points: list[str]
    source_title: str | None
    body: str


class Thread(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class Source(BaseModel):
    """A note the agent retrieved while answering. Cited in the text as `[note:<first 8 hex of id>]`."""

    id: UUID
    title: str
    source_url: str | None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    sources: list[Source] = []


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: UUID | None = None  # omit to start a new thread
