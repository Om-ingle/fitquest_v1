from app.core.config import Settings


def test_settings_reads_database_url_from_env(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:secret-password@db.example.supabase.co:5432/postgres",
    )
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql://")
    assert "secret-password" not in settings.app_name


def test_settings_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
