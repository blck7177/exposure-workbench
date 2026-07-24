"""External-world provider adapters.

Providers are the ONLY code allowed to talk to external services (SEC/EDGAR,
yfinance, Tavily, embeddings). They return plain DTOs; third-party objects never
leak upward. Only `services/*_ingestion` may import from this package — never
routes, agents, analytics, or tools (enforced by the import-direction rule).
"""
