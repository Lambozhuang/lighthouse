"""The chat agent: a two-node LangGraph loop with its conversation state kept in Postgres.

    START -> call_model -> (tool calls?) -> run_tools -> call_model -> ... -> END

Same shape as playground/graph_loop.py, plus three things a served agent needs: a system prompt,
async nodes, and a checkpointer, so that a thread's messages survive between requests.

Thinking blocks. The chat model (Claude Sonnet 5.5) always thinks, and each thinking block must
be sent back unchanged on later requests. `ChatLiteLLM` (langchain-litellm, verified with 0.11.2)
does that: it keeps the signed blocks in `AIMessage.additional_kwargs["thinking_blocks"]`, the
checkpoint stores them with the message, and it replays them when the history before them is
exactly what the model saw. That last condition is why this module never edits history: the
system prompt is a constant, the tool list is fixed, and messages are only ever appended. If the
history does change (say, the prompt is edited in a new release), ChatLiteLLM leaves the old
blocks out rather than send blocks the API would reject; the model then just answers without
its earlier reasoning. tests/test_chat_thinking.py pins this behaviour down.
"""

import asyncio
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from lighthouse.agent.prompts import SYSTEM_PROMPT
from lighthouse.agent.tools import TOOLS
from lighthouse.llm import chat_model


# --- State: the one thing every node reads and updates ---
class State(TypedDict):
    # add_messages is the reducer: a node's returned messages are appended, not overwritten
    messages: Annotated[list[AnyMessage], add_messages]


Agent = CompiledStateGraph[State, None, State, State]


# --- Nodes: take the state, return only what changed ---
async def call_model(state: State, config: RunnableConfig) -> dict[str, list[AnyMessage]]:
    model = chat_model().bind_tools(list(TOOLS.values()))
    # The system prompt is put in front on every call instead of being stored in the state.
    # Passing `config` on is what lets LangGraph stream this call's tokens and Langfuse trace it.
    response = await model.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]], config)
    return {"messages": [response]}


async def _run_tool(call: ToolCall, config: RunnableConfig) -> ToolMessage:
    try:
        # Invoked with the whole tool call (not just its args), a tool returns a ToolMessage
        # carrying both the text for the model and the artifact. `config` holds the user id.
        return await TOOLS[call["name"]].ainvoke(call, config)
    except Exception as e:
        # Unknown tool, bad arguments, database error: tell the model instead of failing the turn.
        return ToolMessage(content=f"error: {e}", tool_call_id=call["id"], name=call["name"], status="error")


async def run_tools(state: State, config: RunnableConfig) -> dict[str, list[AnyMessage]]:
    last = state["messages"][-1]
    assert isinstance(last, AIMessage)
    # The model may ask for several searches at once; run them side by side, keep their order.
    results = await asyncio.gather(*(_run_tool(call, config) for call in last.tool_calls))
    return {"messages": list(results)}


# --- Edges: what runs next ---
def route(state: State) -> str:
    last = state["messages"][-1]
    return "run_tools" if isinstance(last, AIMessage) and last.tool_calls else END


def build_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Agent:
    builder = StateGraph(State)
    builder.add_node("call_model", call_model)
    builder.add_node("run_tools", run_tools)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", route, ["run_tools", END])
    builder.add_edge("run_tools", "call_model")  # this edge is the loop
    return builder.compile(checkpointer=checkpointer)


async def close_interrupted_turn(agent: Agent, config: RunnableConfig) -> None:
    """Make a thread whose last turn was cut off usable again.

    If a turn stops between the model asking for tools and the tools answering (the browser tab
    was closed, the server restarted), the saved history ends with tool calls that have no
    results, and the API rejects any request that continues from there. Answer those calls with
    an error result, appended like any other message, so the next turn starts from valid history.
    """
    state = await agent.aget_state(config)
    messages = state.values.get("messages", [])
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage) and last.tool_calls:
        cancelled = [
            ToolMessage(content="error: interrupted before this tool ran", tool_call_id=call["id"], status="error")
            for call in last.tool_calls
        ]
        await agent.aupdate_state(config, {"messages": cancelled}, as_node="run_tools")


# --- The running agent: one checkpointer pool and one compiled graph per process ---
#
# LangGraph's Postgres checkpointer creates its tables unqualified, so they land in the first
# schema of the connection's search_path. They must not be in `public`: PostgREST serves that
# schema to anyone holding the anon key. So the checkpointer gets its own small pool whose
# connections have search_path set to the internal `lighthouse` schema. (The main pool in
# lighthouse.db cannot be reused: its connections need `public` first.) The setting travels as a
# connection option, which needs a direct or session-mode connection to Postgres; a
# transaction-mode pooler in front of the database would not carry it.
#
# Checkpoints carry no user id. Who owns a conversation is decided by its `public.threads` row,
# which is under row level security; the API checks that row first and then uses its id as the
# checkpoint thread_id.

_pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
_saver: AsyncPostgresSaver | None = None
_agent: Agent | None = None


async def open_agent(database_url: str, *, max_size: int = 5) -> None:
    global _pool, _saver, _agent
    if _agent is not None:
        return
    _pool = AsyncConnectionPool(
        database_url,
        connection_class=AsyncConnection[DictRow],
        # autocommit and dict_row are what AsyncPostgresSaver requires of its connections.
        kwargs={"autocommit": True, "row_factory": dict_row, "options": "-c search_path=lighthouse"},
        min_size=1,
        max_size=max_size,
        open=False,
    )
    await _pool.open()
    _saver = AsyncPostgresSaver(_pool)
    await _saver.setup()  # creates or migrates the checkpoint tables; safe to run on every start
    _agent = build_graph(_saver)


async def close_agent() -> None:
    global _pool, _saver, _agent
    if _pool is not None:
        await _pool.close()
    _pool = _saver = _agent = None


def agent() -> Agent:
    if _agent is None:
        raise RuntimeError("agent is not open")
    return _agent


def checkpointer() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError("agent is not open")
    return _saver
