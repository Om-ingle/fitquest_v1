from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# M11 — environments in which the production auth configuration checks below
# are relaxed. A developer machine or CI runner has no production Supabase
# project to point at, and tests verify tokens against an injected JWKS.
_DEVELOPMENT_ENVIRONMENTS = frozenset({"development", "dev", "local", "test"})


class Settings(BaseSettings):
    app_name: str = "FitQuest API"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"

    # Which deployment this process is. Non-development values enable the
    # fail-fast configuration checks at the bottom of this class (F-12).
    environment: str = "development"

    # PostgreSQL connection string (Supabase). Required — no silent fallback.
    # Example: postgresql://postgres:PASSWORD@db.<project-ref>.supabase.co:5432/postgres
    database_url: str

    # Backend-only Supabase values. `supabase_url` doubles as the M11 identity
    # issuer and JWKS source, so it is REQUIRED outside development.
    supabase_url: str | None = None
    supabase_secret_key: str | None = None

    # ── Authentication (M11 / F-04) ────────────────────────────────────────
    # There is deliberately NO shared JWT secret here. Supabase signs access
    # tokens with the project's asymmetric ES256 key and publishes the public
    # half as a JWKS document; verification fetches that document, so the
    # backend holds no secret capable of minting a token. The previous
    # `supabase_jwt_secret = "change-me"` default was removed with F-12: a
    # published default secret turns bearer auth into a forgery kit.
    #
    # How long the fetched JWKS document is trusted before it is re-fetched.
    # An unknown `kid` always forces one refresh first, so a key rotation is
    # picked up immediately rather than after this window.
    supabase_jwks_cache_seconds: float = 3600.0

    # F-18 — users allowed to ingest into the RAG knowledge base, as a
    # comma-separated list of Supabase Auth subjects (`auth.users.id`). Empty
    # means nobody, which is the correct default: ingestion is a privileged
    # write into the vector store. Admin is an allow-list, not a schema column,
    # because M11 introduces exactly one privileged operation.
    admin_user_ids: str = ""

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

    # ── Real-time AI coaching push (M8.3A) ──────────────────────────────
    # Bounds on the background trigger -> AI coaching -> WebSocket push
    # stage. Conservative + in-process on purpose (SRS §17 treats Redis as
    # optional): at most one generation per user per cooldown window, so a
    # burst (a run that also captures hexes and crosses a milestone) folds
    # into one push instead of paying per trigger. Workers bound concurrent
    # LLM calls. Tests disable the whole stage via push_coach.enabled=False.
    push_coach_enabled: bool = True
    push_coach_cooldown_seconds: float = 30.0
    push_coach_max_workers: int = 2

    # Look for .env next to the API first, then at the repository root, so the
    # app works whether it is run from apps/api or the repo root. The master
    # .env also holds Android-side variables (MAPTILER_API_KEY etc.) — ignore
    # anything this backend doesn't declare.
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Derived authentication configuration ───────────────────────────────

    @property
    def is_development(self) -> bool:
        return self.environment.strip().lower() in _DEVELOPMENT_ENVIRONMENTS

    def _supabase_base(self) -> str | None:
        url = (self.supabase_url or "").strip()
        return url.rstrip("/") or None

    @property
    def supabase_jwks_url(self) -> str | None:
        """Public verification keys for Supabase-issued access tokens."""
        base = self._supabase_base()
        return f"{base}/auth/v1/.well-known/jwks.json" if base else None

    @property
    def supabase_jwt_issuer(self) -> str | None:
        """Expected `iss` claim. Supabase issues `{project_url}/auth/v1`."""
        base = self._supabase_base()
        return f"{base}/auth/v1" if base else None

    @property
    def admin_user_id_set(self) -> frozenset[str]:
        """Parsed `ADMIN_USER_IDS` allow-list (subjects, never internal ids)."""
        return frozenset(
            part.strip() for part in self.admin_user_ids.split(",") if part.strip()
        )

    @model_validator(mode="after")
    def _require_auth_configuration_outside_development(self) -> "Settings":
        """Fail fast rather than start an API that cannot verify a token (F-12).

        A production process without SUPABASE_URL has no issuer to check and no
        JWKS to fetch, so every authenticated route would answer 503 — or, far
        worse, someone would be tempted to "fix" it by trusting the token. It is
        better to refuse to boot.
        """
        if not self.is_development and self._supabase_base() is None:
            raise ValueError(
                "SUPABASE_URL is required when ENVIRONMENT is not a development "
                "value: it is the issuer and JWKS source for bearer-token "
                "verification (M11 / F-12)."
            )
        return self


settings = Settings()
