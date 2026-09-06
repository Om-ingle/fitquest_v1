from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FitQuest API"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"

    # PostgreSQL connection string (Supabase). Required — no silent fallback.
    # Example: postgresql://postgres:PASSWORD@db.<project-ref>.supabase.co:5432/postgres
    database_url: str

    # Backend-only Supabase values. Optional in Phase 1 (the app talks to the
    # database directly via DATABASE_URL); kept here so later phases can use
    # them without another config change.
    supabase_url: str | None = None
    supabase_secret_key: str | None = None
    supabase_jwt_secret: str = "change-me"

    # ── AI providers (Phase 4C.2) ──────────────────────────────────────────
    # Backend-only. The key lives in .env as GEMINI_API_KEY and must NEVER be
    # sent to Android, logged, or echoed in responses/errors.
    # One provider (Google Gemini) covers BOTH embeddings and the LLM, per
    # SRS §14 — see app/modules/rag/README.md for the rationale.
    gemini_api_key: str | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_llm_model: str = "gemini-2.5-flash"
    embedding_timeout_seconds: float = 30.0
    llm_timeout_seconds: float = 30.0

    # ── AI provider selection (Phase 4C.3B device-test fallback) ─────────
    # Which LLM generates the coach text. `gemini` (default) or
    # `agentrouter` — an OpenAI-compatible gateway (e.g. DeepSeek) behind
    # the AGENTIC_API_KEY + AGENTROUTER_BASE_URL pair. Embeddings stay on
    # Gemini (gemini-embedding-001) in BOTH modes: the pgvector schema is
    # frozen to 1536 dims and embedding quota is separate from text
    # generation. See app/modules/coach/llm.py `get_llm_provider()`.
    llm_provider: str = "gemini"
    agentic_api_key: str | None = None
    agentrouter_base_url: str | None = None
    agentrouter_model: str = "deepseek-v4-flash"

    # Retrieval/coach tuning (Phase 4C.2; threshold recalibrated 4C.3A).
    # 0.50 from the 2026-09-06 live calibration probe (13 queries against
    # the real corpus): on-topic chunk similarities 0.60-0.77, clearly
    # unrelated queries 0.43-0.46 — an empty band 0.50 sits in the middle
    # of, ~0.10 margin on each side. See rag/README.md "Retrieval quality
    # evaluation". Too-high a threshold degrades to the honest
    # grounded=false fallback; too-low admits unrelated text as knowledge.
    rag_similarity_threshold: float = 0.50
    coach_top_k: int = 4

    # Look for .env next to the API first, then at the repository root, so the
    # app works whether it is run from apps/api or the repo root. The master
    # .env also holds Android-side variables (MAPTILER_API_KEY etc.) — ignore
    # anything this backend doesn't declare.
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
