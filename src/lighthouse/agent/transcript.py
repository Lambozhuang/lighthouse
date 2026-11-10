"""From the agent's raw message list to what the web app shows.

A thread's state holds everything: user messages, the model's tool calls, tool results, answers.
The web app wants two things out of it: the visible conversation, and for each answer the notes
needed to resolve its `[note:xxxxxxxx]` markers.

Both the live stream (api/chat.py) and the history endpoint (api/threads.py) use this module, so
a reloaded conversation reads the same as it did while streaming.
"""

import re
from collections.abc import Iterable

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from lighthouse.schemas import ChatMessage, Source

# Within one turn the model can write text more than once (a remark before a tool call, then the
# answer). The pieces are shown as separate paragraphs.
PARAGRAPH_BREAK = "\n\n"

_CITATION = re.compile(r"\[note:([0-9a-f]{8})\]")


def _short_id(source: Source) -> str:
    return source.id.hex[:8]


def sources_from(messages: Iterable[AnyMessage]) -> list[Source]:
    """The notes behind the tool results in `messages`: each note once, in order of first use."""
    found: dict[str, Source] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.artifact, list):
            for item in message.artifact:
                source = Source.model_validate(item)
                found.setdefault(_short_id(source), source)
    return list(found.values())


def to_chat_messages(messages: Iterable[AnyMessage]) -> list[ChatMessage]:
    """User and assistant text only; tool calls and tool results become each answer's `sources`.

    An answer's sources are the notes its own turn retrieved. A follow-up answer often cites a
    note found in an earlier turn without searching again (the tool result is still in the
    model's context), so notes from earlier turns are added when the answer cites them.
    Otherwise the web app could not resolve that marker.
    """
    result: list[ChatMessage] = []
    turn: list[AnyMessage] = []  # what the agent produced since the last user message
    earlier: dict[str, Source] = {}  # short id -> note, from the turns already closed

    def close_turn() -> None:
        retrieved = {_short_id(source): source for source in sources_from(turn)}
        # `.text` is the message's text blocks only: no thinking, no tool calls.
        texts = [message.text for message in turn if isinstance(message, AIMessage) and message.text]
        if texts:
            content = PARAGRAPH_BREAK.join(texts)
            cited = dict.fromkeys(_CITATION.findall(content))  # in order, without repeats
            carried_over = [earlier[marker] for marker in cited if marker in earlier and marker not in retrieved]
            result.append(ChatMessage(role="assistant", content=content, sources=[*retrieved.values(), *carried_over]))
        earlier.update(retrieved)
        turn.clear()

    for message in messages:
        if isinstance(message, HumanMessage):
            close_turn()
            result.append(ChatMessage(role="user", content=message.text))
        else:
            turn.append(message)
    close_turn()
    return result
