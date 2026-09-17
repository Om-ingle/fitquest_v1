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


def test_the_suite_cannot_reach_a_real_ai_provider():
    """Guard for the neutralisation in conftest.

    Provider credentials are emptied there before the app is imported, which is
    the only reason a developer's own .env cannot configure a live provider for
    the whole suite. That ordering is invisible and easy to break — moving the
    block below the app import, or deleting it, restores the exact conditions
    that produced CI run #1's single red test. Asserting on the live settings
    object is what makes the break loud.
    """
    from app.core.config import settings

    assert not settings.gemini_api_key
    assert not settings.agentic_api_key


def test_a_dotenv_file_cannot_supply_a_provider_credential(tmp_path):
    """The neutralisation outranks .env, which is the whole point of it.

    Settings loads `env_file=(".env", "../../.env")`, so a real key sitting in a
    developer's apps/api/.env is read by every test process. Environment
    variables outrank the dotenv file in pydantic-settings; this asserts that
    precedence holds, using a .env the test writes itself so it does not depend
    on whether the developer has one.
    """
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "GEMINI_API_KEY=sk-a-real-key-that-tests-must-never-use\n"
        "AGENTIC_API_KEY=sk-a-real-key-that-tests-must-never-use\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=str(dotenv))

    assert not settings.gemini_api_key
    assert not settings.agentic_api_key
