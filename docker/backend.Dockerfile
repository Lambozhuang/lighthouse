# syntax=docker/dockerfile:1
# Backend image, used by three compose services: migrate, api and worker.
# Build context is the repository root:  docker build -f docker/backend.Dockerfile .

# --- Stage 1: install the locked dependencies into a virtualenv with uv ------------------------
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv

# Compile .pyc files now (faster start); copy instead of hard-linking out of the cache mount;
# never download another Python, use the image's.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer is rebuilt only when pyproject.toml or uv.lock change.
# --frozen: install exactly what uv.lock says, fail rather than re-resolve.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Then the project itself, as a normal (non-editable) install, so the final image does not
# need the source tree.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- Stage 2: the runtime image: Python, the virtualenv and the SQL migrations ------------------
FROM python:3.12-slim

RUN useradd --uid 10001 --create-home app
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY supabase/migrations ./supabase/migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LIGHTHOUSE_MIGRATIONS_DIR=/app/supabase/migrations

USER app
EXPOSE 8080

# Default command is the API; compose overrides it for `migrate` and `worker`.
CMD ["uvicorn", "lighthouse.main:app", "--host", "0.0.0.0", "--port", "8080"]
