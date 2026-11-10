"""Exercise: the same agent as agent_loop.py, rebuilt as a LangGraph graph.

Run from the repo root:  uv run playground/graph_loop.py "what time is it, and what is 17*23?"
Set DUMP=1 to print each node's state update as the graph runs.
"""

import os
import subprocess
import sys
from datetime import datetime
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

load_dotenv()  # reads ANTHROPIC_API_KEY and LIGHTHOUSE_MODEL from .env
DUMP = bool(os.environ.get("DUMP"))


# --- 1. Tools: @tool builds the schema from the signature and docstring ---
@tool
def now() -> str:
    """Current local date and time."""
    return datetime.now().isoformat(timespec="seconds")


@tool
def calc(expr: str) -> str:
    """Evaluate an arithmetic expression, e.g. '17*23'."""
    # bc instead of eval(): the model controls the input
    out = subprocess.run(["bc", "-l"], input=expr + "\n", text=True, capture_output=True)
    return out.stdout.strip() or f"error: {out.stderr.strip()}"


TOOLS = {t.name: t for t in (now, calc)}
model = ChatLiteLLM(model=os.environ["LIGHTHOUSE_MODEL"], max_tokens=4096).bind_tools(list(TOOLS.values()))


# --- 2. State: the one thing every node reads and updates ---
class State(TypedDict):
    # add_messages is the reducer: a node's returned messages are appended, not overwritten
    messages: Annotated[list[AnyMessage], add_messages]


# --- 3. Nodes: take the state, return only what changed ---
def call_model(state: State) -> dict[str, list[AnyMessage]]:
    return {"messages": [model.invoke(state["messages"])]}


def run_tools(state: State) -> dict[str, list[AnyMessage]]:
    last = state["messages"][-1]
    assert isinstance(last, AIMessage)
    results: list[AnyMessage] = []
    for call in last.tool_calls:
        try:
            content = str(TOOLS[call["name"]].invoke(call["args"]))
            results.append(ToolMessage(content=content, tool_call_id=call["id"]))
        except Exception as e:
            results.append(ToolMessage(content=f"error: {e}", tool_call_id=call["id"], status="error"))
    return {"messages": results}


# --- 4. Edges: what runs next ---
def route(state: State) -> str:
    last = state["messages"][-1]
    return "run_tools" if isinstance(last, AIMessage) and last.tool_calls else END


builder = StateGraph(State)
builder.add_node("call_model", call_model)
builder.add_node("run_tools", run_tools)
builder.add_edge(START, "call_model")
builder.add_conditional_edges("call_model", route, ["run_tools", END])
builder.add_edge("run_tools", "call_model")  # this edge is the loop
graph = builder.compile()


def agent(user_input: str) -> str:
    start: State = {"messages": [HumanMessage(user_input)]}
    if not DUMP:
        return str(graph.invoke(start)["messages"][-1].content)
    # stream_mode="updates" yields {node_name: that node's returned update} after each step
    final = ""
    for step in graph.stream(start, stream_mode="updates"):
        for node, update in step.items():
            print(f"\n===== node {node} returned {len(update['messages'])} message(s) =====", file=sys.stderr)
            for m in update["messages"]:
                print(m.pretty_repr(), file=sys.stderr)
                final = str(m.content)
    return final


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "What time is it, and what is 17*23?"
    print(agent(question))
