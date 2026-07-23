"""Application settings loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
    database_url_sync: str = "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench"

    # LLM
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-3-5-haiku-20241022"
    embedding_model: str = "text-embedding-3-small"   # 1536-dim, filing_chunks (M5)

    # External providers (Issuer Intelligence)
    tavily_api_key: str = ""
    edgar_identity: str = ""   # SEC requires a UA with contact, e.g. "Name email@x.com"

    # Agent budgets (env-overridable; see IMPLEMENTATION_PLAN §0.5)
    session_tool_budget: int = 40       # tool calls per agent session
    external_search_budget: int = 5     # Tavily searches per research run
    submit_brief_retries: int = 2       # submit_brief citation-gate retries
    respond_retries: int = 1            # respond citation-gate retries

    # Agent mode
    report_agent_mode: str = "direct_llm"

    # App
    demo_mode: bool = True
    log_level: str = "INFO"
    worker_poll_interval: int = 2

    # CORS
    cors_origins: str = "http://localhost:3103,http://127.0.0.1:3103"

    # Paths
    data_dir: Path = Path("/app/data")
    configs_dir: Path = Path("/app/configs")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
