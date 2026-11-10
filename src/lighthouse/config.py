"""Settings, read once from the environment (and `.env` in development)."""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# LiteLLM and Langfuse read their keys straight from os.environ, so load .env into it as well.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres (the Supabase database). The API connects as the table owner and switches to the
    # `authenticated` role per request; see db.user_conn.
    database_url: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    # Secret Supabase Auth signs access tokens with (HS256).
    jwt_secret: str = Field(default="", repr=False)

    # Models, all called through LiteLLM ("provider/model").
    chat_model: str = Field(default="anthropic/claude-sonnet-5-5", validation_alias="LIGHTHOUSE_MODEL")
    distill_model: str = Field(default="anthropic/claude-haiku-5-5", validation_alias="LIGHTHOUSE_DISTILL_MODEL")
    embedding_model: str = Field(
        default="openrouter/openai/text-embedding-3-small", validation_alias="LIGHTHOUSE_EMBEDDING_MODEL"
    )
    embedding_dimensions: int = 1536  # must match vector(1536) in the migration

    # Tracing is on only when both Langfuse keys are present.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = Field(default="", repr=False)

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Worker
    worker_poll_seconds: float = 2.0
    worker_max_attempts: int = 3

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
