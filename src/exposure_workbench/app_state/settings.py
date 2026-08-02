"""Application settings loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
    # V2-C: runtime connects as the non-owner role app_rls so RLS policies bind.
    # Empty => fall back to database_url (offline tests / pre-RLS local dev).
    database_url_app: str = ""

    # LLM
    openai_api_key: str = ""
    # gpt-5.x takes max_completion_tokens rather than max_tokens and accepts only
    # the default temperature — see llm/client.py, which branches on the prefix.
    openai_model: str = "gpt-5.4-mini"
    embedding_model: str = "text-embedding-3-small"   # 1536-dim, filing_chunks (M5)

    # External providers (Issuer Intelligence)
    tavily_api_key: str = ""
    edgar_identity: str = ""   # SEC requires a UA with contact, e.g. "Name email@x.com"

    # Identity (Clerk — V2-A). Verification is JWKS-only; no secret key needed.
    clerk_issuer: str = ""                 # e.g. https://xxxx.clerk.accounts.dev
    clerk_authorized_parties: str = ""     # comma-sep origins allowed as azp, e.g. http://localhost:3103

    # Agent budgets (env-overridable; see IMPLEMENTATION_PLAN §0.5)
    session_tool_budget: int = 40       # tool calls per SESSION (research; and any
                                        # session with no per-turn budget of its own)
    external_search_budget: int = 5     # Tavily searches per research run
    # V3-B2: tool calls per TURN, for sessions that have turns. A lifetime budget
    # is the wrong shape for a conversation — it does not run out, it makes the
    # session progressively less able to answer, with no signal to the user. The
    # value is stamped on the row at creation (agent_sessions.turn_tool_budget),
    # so which regime a session is under is data, not a branch in reserve().
    turn_tool_budget: int = 15

    # V3-B1: refuse a turn whose prompt would exceed this, BEFORE charging quota.
    # Deliberately conservative and measured before it is relaxed: B0 records the
    # real distribution (agent_sessions.last_prompt_tokens) and B3's summarisation
    # is only built if that data says it is needed.
    context_soft_limit_tokens: int = 80_000

    # Agent mode
    report_agent_mode: str = "direct_llm"

    # App
    demo_mode: bool = True
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
    # V2-H. Three actions that created rows with nothing bounding them.
    # 5 creates/day sits under MAX_PORTFOLIOS_PER_USER=20, so the lifetime
    # ceiling is reached over days rather than in one scripted loop — the two
    # are orthogonal and both stay. 10 uploads matches daily_market_syncs:
    # both are "one action buys a bounded pile of provider calls", and an
    # upload can drive up to ~400 yfinance requests inside one request.
    daily_portfolio_creates: int = 5
    daily_position_uploads: int = 10
    daily_agent_sessions: int = 5

    global_daily_chat_turns: int = 200
    global_daily_research_runs: int = 30
    global_daily_readiness: int = 100
    global_daily_exposure_runs: int = 200
    global_daily_market_syncs: int = 50
    global_daily_portfolio_creates: int = 100
    global_daily_position_uploads: int = 100
    global_daily_agent_sessions: int = 100

    # Price freshness (V2-E5). Calendar days, so ~10 covers a long weekend plus a
    # holiday and still catches a genuinely dead ticker. A holding whose newest
    # bar is older than this fails the run instead of being valued at a stale
    # price — the judgement lives in exactly one place, _validate_inputs.
    price_staleness_days: int = 10

    # CORS
    cors_origins: str = "http://localhost:3103,http://127.0.0.1:3103"

    # Paths
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
