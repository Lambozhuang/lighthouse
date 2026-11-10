"""The two tools the chat agent has: search the notes, and read one note.

Each tool returns a pair (`response_format="content_and_artifact"`):

- the content is the text the model reads: distilled note fields only (see lighthouse.retrieval);
- the artifact is the list of notes behind that text, as `Source` dicts. The model never sees
  it; the API collects artifacts to tell the web app which notes a turn retrieved.

Whose notes are read is decided by `config["configurable"]["user_id"]`, which the API sets from
the verified access token. It is not a tool argument, so nothing the model writes (or is tricked
into writing) can point a tool at another user's notes. LangChain fills in a parameter annotated
`RunnableConfig` itself and leaves it out of the schema the model is shown.
"""

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from lighthouse import db, retrieval
from lighthouse.retrieval import DistilledNote
from lighthouse.schemas import Source

SEARCH_LIMIT = 5

SourceDicts = list[dict[str, Any]]


def _user_id(config: RunnableConfig) -> UUID:
    return UUID(config.get("configurable", {})["user_id"])


def _source(note: DistilledNote) -> dict[str, Any]:
    # mode="json" turns the UUID into a string, so the artifact is plain data in the checkpoint.
    return Source(id=note.id, title=note.title, source_url=note.source_url).model_dump(mode="json")


def format_note(note: DistilledNote) -> str:
    """A note as text for the model. Starts with the marker the answer should cite it by."""
    lines = [f"[note:{note.short_id}] {note.title}", f"Saved: {note.created_at:%Y-%m-%d}", f"Summary: {note.summary}"]
    if note.key_points:
        lines.append("Key points:")
        lines += [f"- {point}" for point in note.key_points]
    if note.tags:
        lines.append("Tags: " + ", ".join(note.tags))
    if note.source_url:
        # Only the host: the page's own title and path are text the page author controls.
        lines.append(f"Source: {urlsplit(note.source_url).hostname or 'web page'}")
    return "\n".join(lines)


@tool(response_format="content_and_artifact")
async def search_notes(query: str, config: RunnableConfig) -> tuple[str, SourceDicts]:
    """Search the user's saved notes by meaning and by keyword. Returns the best matching notes
    (title, summary, key points, tags, source). Search with the topic or the key terms of the
    question; try different wording if the first search finds nothing useful."""
    async with db.user_conn(_user_id(config)) as conn:
        notes = await retrieval.search_notes(conn, query, SEARCH_LIMIT)
    if not notes:
        return "No notes matched.", []
    return "\n\n".join(format_note(note) for note in notes), [_source(note) for note in notes]


@tool(response_format="content_and_artifact")
async def get_note(note_id: str, config: RunnableConfig) -> tuple[str, SourceDicts]:
    """Read one note by id: either the 8-character id from a [note:xxxxxxxx] marker or the full id."""
    # Models sometimes pass the whole marker; accept "[note:1a2b3c4d]" as well as "1a2b3c4d".
    cleaned = note_id.strip().strip("[]").removeprefix("note:")
    async with db.user_conn(_user_id(config)) as conn:
        note = await retrieval.get_note(conn, cleaned)
    if note is None:
        return f"No note with id {note_id!r}.", []
    return format_note(note), [_source(note)]


TOOLS: dict[str, BaseTool] = {t.name: t for t in (search_notes, get_note)}
