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
