"""Application settings loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
    database_url_sync: str = "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench"
    # V2-C: runtime connects as the non-owner role app_rls so RLS policies bind.
    # Empty => fall back to database_url (offline tests / pre-RLS local dev).
    database_url_app: str = ""

    # LLM
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-3-5-haiku-20241022"
    embedding_model: str = "text-embedding-3-small"   # 1536-dim, filing_chunks (M5)

    # External providers (Issuer Intelligence)
    tavily_api_key: str = ""
    edgar_identity: str = ""   # SEC requires a UA with contact, e.g. "Name email@x.com"

    # Identity (Clerk — V2-A). Verification is JWKS-only; no secret key needed.
    clerk_issuer: str = ""                 # e.g. https://xxxx.clerk.accounts.dev
    clerk_authorized_parties: str = ""     # comma-sep origins allowed as azp, e.g. http://localhost:3103

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

    # Concurrency (V2-E). Leases rely on "pick a generous value, let expiry
    # self-heal" — there is deliberately no heartbeat or renewal thread, so the
    # only failure mode is a dead task sitting a while, never a live one being
    # stolen. 1800s is comfortably longer than the slowest real task (a cold
    # issuer_research: EDGAR ingest + embeddings + a 30-turn agent loop).
    task_lease_seconds: int = 1800
    task_max_retries: int = 3
    # One in-flight turn per agent session. Generous on purpose: a legitimate
    # 16-turn LLM loop must never have its lease stolen, and the worst case for a
    # turn whose process died is that its session is stuck for this long.
    turn_lease_seconds: int = 900

    # Daily quota (V2-E3). The unit is a USER ACTION — not tokens, not tool
    # calls. Orthogonal to the per-session budgets above: those bound one
    # conversation, these bound one day. Every action is charged twice, once to
    # the user's pool and once to the shared '_global' backstop row.
    daily_chat_turns: int = 10
    daily_research_runs: int = 3
    daily_readiness: int = 10
    daily_exposure_runs: int = 20
    daily_market_syncs: int = 10

    global_daily_chat_turns: int = 200
    global_daily_research_runs: int = 30
    global_daily_readiness: int = 100
    global_daily_exposure_runs: int = 200
    global_daily_market_syncs: int = 50

    # CORS
    cors_origins: str = "http://localhost:3103,http://127.0.0.1:3103"

    # Paths
    data_dir: Path = Path("/app/data")
    configs_dir: Path = Path("/app/configs")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def clerk_authorized_parties_list(self) -> list[str]:
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
