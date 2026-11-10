"""Model access. Everything goes through LiteLLM, so a model is just a "provider/model" string.

- `chat_model()` / `distill_model()`: LangChain chat models (used by the agent graph and the
  distill step), so one Langfuse callback traces both.
- `embed_texts()`: embeddings for note chunks and for search queries.
- `trace_config()`: the LangChain `config` that sends a run to Langfuse, or an empty one when
  tracing is not configured.
"""

from typing import Any, Literal

import litellm
from langchain_core.runnables import RunnableConfig
from langchain_litellm import ChatLiteLLM

from lighthouse.config import get_settings

litellm.drop_params = True  # ignore parameters a provider does not support instead of failing


def chat_model(**kwargs: Any) -> ChatLiteLLM:
    return ChatLiteLLM(model=get_settings().chat_model, max_tokens=8000, **kwargs)


def distill_model(**kwargs: Any) -> ChatLiteLLM:
    return ChatLiteLLM(model=get_settings().distill_model, max_tokens=4000, **kwargs)


async def embed_texts(texts: list[str], *, input_type: Literal["document", "query"] = "document") -> list[list[float]]:
    """One vector per text, in order. `input_type` is recorded in the trace only: this embedding
    model uses the same space for documents and queries."""
    if not texts:
        return []
    settings = get_settings()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), 64):  # keep each request small
        batch = texts[start : start + 64]
        response = await litellm.aembedding(model=settings.embedding_model, input=batch)
        data = sorted(response.data, key=lambda item: item["index"])
        vectors.extend(item["embedding"] for item in data)
    if vectors and len(vectors[0]) != settings.embedding_dimensions:
        raise RuntimeError(
            f"{settings.embedding_model} returned {len(vectors[0])} dimensions, "
            f"but the note_chunks.embedding column is vector({settings.embedding_dimensions})"
        )
    return vectors


def trace_config(
    name: str, *, user_id: str | None = None, session_id: str | None = None, tags: list[str] | None = None
) -> RunnableConfig:
    """Pass as `config=` to a LangChain / LangGraph call to get one Langfuse trace for that run."""
    config: RunnableConfig = {"run_name": name}
    if not get_settings().tracing_enabled:
        return config
    from langfuse.langchain import CallbackHandler

    config["callbacks"] = [CallbackHandler()]
    metadata: dict[str, Any] = {}
    if user_id:
        metadata["langfuse_user_id"] = user_id
    if session_id:
        metadata["langfuse_session_id"] = session_id
    if tags:
        metadata["langfuse_tags"] = tags
    config["metadata"] = metadata
    return config
