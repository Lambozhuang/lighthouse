"""Thinking blocks survive a tool call and a checkpoint.

Claude Sonnet 5.5 always thinks, and wants each thinking block back unchanged on later requests
of the same conversation. The agent relies on `ChatLiteLLM` for that (see the note at the top of
lighthouse/agent/graph.py). Nothing in our own code would fail if a dependency upgrade stopped
doing it; the model would just quietly lose its earlier reasoning. So this test checks the
dependency: LiteLLM itself is replaced by a stub that returns a canned reply and records what
it is sent. No network.
"""

from typing import Any

import litellm
import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

pytestmark = pytest.mark.asyncio(loop_scope="session")

MODEL = "anthropic/claude-sonnet-5-5"
THINKING_BLOCK = {"type": "thinking", "thinking": "", "signature": "signed-by-the-api"}


@tool
def search_notes(query: str) -> str:
    """Search the user's notes."""
    return "nothing"


def _tool_call_reply() -> litellm.ModelResponse:
    """What LiteLLM returns for a reply that thinks and then calls a tool."""
    call = {"id": "toolu_1", "type": "function", "function": {"name": "search_notes", "arguments": '{"query": "tea"}'}}
    message = {"role": "assistant", "content": None, "tool_calls": [call], "thinking_blocks": [THINKING_BLOCK]}
    return litellm.ModelResponse(model=MODEL, choices=[{"index": 0, "finish_reason": "tool_calls", "message": message}])


async def test_thinking_blocks_are_stored_and_sent_back(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[list[dict[str, Any]]] = []

    async def fake_acompletion(**kwargs: Any) -> litellm.ModelResponse:
        requests.append(kwargs["messages"])
        return _tool_call_reply()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.delenv("ANTHROPIC_API_BASE", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    model = ChatLiteLLM(model=MODEL).bind_tools([search_notes])

    history: list[AnyMessage] = [SystemMessage("Answer from the notes."), HumanMessage("What tea do I like?")]
    reply = await model.ainvoke(history)
    assert isinstance(reply, AIMessage) and reply.tool_calls
    [stored] = reply.additional_kwargs["thinking_blocks"]
    assert stored["signature"] == THINKING_BLOCK["signature"]

    # A Postgres checkpoint serializes the messages between the two model calls of a turn.
    serde = JsonPlusSerializer()
    history = serde.loads_typed(serde.dumps_typed([*history, reply, ToolMessage("nothing", tool_call_id="toolu_1")]))
    await model.ainvoke(history)

    [assistant_turn] = [message for message in requests[1] if message["role"] == "assistant"]
    assert assistant_turn["thinking_blocks"] == [THINKING_BLOCK]

    # And when the history in front of a block is no longer what the model saw (here: an edited
    # system prompt), the block is left out instead of being sent to an API that would reject it.
    history[0] = SystemMessage("A different prompt.")
    await model.ainvoke(history)
    [assistant_turn] = [message for message in requests[2] if message["role"] == "assistant"]
    assert not assistant_turn.get("thinking_blocks")
