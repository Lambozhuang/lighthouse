"""Exercise: a bare agent loop with the raw Anthropic SDK, no framework.

Run from the repo root (after `uv sync`):  uv run playground/agent_loop.py "what time is it, and what is 17*23?"
Set DUMP=1 to print the full messages list before every model call.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam
from dotenv import load_dotenv

load_dotenv()  # reads ANTHROPIC_API_KEY from .env
client = anthropic.Anthropic()
MODEL = "claude-haiku-5-5"
DUMP = bool(os.environ.get("DUMP"))


def summarize(content: Any) -> str:
    """One-line description of a message's content: a plain string, or which blocks it holds."""
    if isinstance(content, str):
        return f'text "{content}"'
    parts: list[str] = []
    for b in content:
        d = b if isinstance(b, dict) else b.model_dump()  # request dicts vs response objects
        match d["type"]:
            case "text":
                parts.append(f'text "{d["text"][:40]}"')
            case "tool_use":
                parts.append(f"tool_use {d['name']}({json.dumps(d['input'])}) id=..{d['id'][-4:]}")
            case "tool_result":
                parts.append(f'tool_result id=..{d["tool_use_id"][-4:]} -> "{d["content"]}"')
            case other:
                parts.append(other)
    return f"{len(parts)} blocks: " + " | ".join(parts)


# --- 1. Tools: a schema the model sees, and a Python function that runs ---
TOOLS: list[ToolParam] = [
    {
        "name": "now",
        "description": "Current local date and time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "calc",
        "description": "Evaluate an arithmetic expression, e.g. '17*23'.",
        "input_schema": {
            "type": "object",
            "properties": {"expr": {"type": "string"}},
            "required": ["expr"],
        },
    },
]


def run_tool(name: str, args: dict[str, Any]) -> str:
    if name == "now":
        return datetime.now().isoformat(timespec="seconds")
    if name == "calc":
        # bc instead of eval(): the model controls the input
        out = subprocess.run(["bc", "-l"], input=args["expr"], text=True, capture_output=True)
        return out.stdout.strip() or f"error: {out.stderr.strip()}"
    raise ValueError(f"unknown tool {name}")


# --- 2. The loop: call model, run tools, feed results back, until it stops ---
def agent(user_input: str) -> str:
    messages: list[MessageParam] = [{"role": "user", "content": user_input}]
    turn = 0
    while True:
        turn += 1
        if DUMP:
            print(f"\n===== call {turn} | SENDING {len(messages)} messages =====", file=sys.stderr)
            for i, m in enumerate(messages, 1):
                print(f"  [{i}] {m['role']:9s} {summarize(m['content'])}", file=sys.stderr)
        resp = client.messages.create(model=MODEL, max_tokens=4096, tools=TOOLS, messages=messages)
        if DUMP:
            print(f"----- call {turn} | RECEIVED stop_reason={resp.stop_reason} -----", file=sys.stderr)
            # response blocks are pydantic models, not dicts; model_dump() turns them into JSON
            print(json.dumps([b.model_dump() for b in resp.content], indent=2, ensure_ascii=False), file=sys.stderr)
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            if resp.stop_reason != "end_turn":
                print(f"[stopped: {resp.stop_reason}]", file=sys.stderr)
            return "".join(b.text for b in resp.content if b.type == "text")

        results: list[ToolResultBlockParam] = []
        for block in resp.content:
            if block.type == "tool_use":
                args = cast(dict[str, Any], block.input)
                print(f"  -> {block.name}({json.dumps(args)})", file=sys.stderr)
                try:
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": run_tool(block.name, args)}
                    )
                except Exception as e:
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": f"error: {e}", "is_error": True}
                    )
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "What time is it, and what is 17*23?"
    print(agent(question))
