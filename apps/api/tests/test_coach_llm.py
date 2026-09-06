"""Phase 4C.2 Gemini LLM-provider tests (httpx mocked — zero API calls)."""
import httpx
import pytest

from app.core.config import settings
from app.modules.coach.llm import (
    AgentRouterLLMProvider,
    LLMProvider,
    LLMProviderError,
    LLMProviderNotConfigured,
    LLMProviderTimeout,
    GeminiLLMProvider,
    MalformedLLMResponse,
    get_llm_provider,
)

DUMMY_KEY = "test-key-do-not-use"


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


def _candidates(text):
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}


def test_generate_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse(_candidates("  Great work — keep walking!  "))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(api_key=DUMMY_KEY, model="gemini-2.5-flash", timeout_seconds=7.0)

    assert provider.generate("prompt text") == "Great work — keep walking!"
    assert "generateContent" in captured["url"]
    assert captured["json"]["contents"][0]["parts"][0]["text"] == "prompt text"
    assert captured["headers"]["x-goog-api-key"] == DUMMY_KEY
    assert DUMMY_KEY not in captured["url"]
    assert captured["timeout"] == 7.0


def test_generate_satisfies_the_protocol(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(_candidates("ok")))
    assert isinstance(GeminiLLMProvider(api_key=DUMMY_KEY), LLMProvider)


def test_malformed_no_candidates(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse({"candidates": []}))
    with pytest.raises(MalformedLLMResponse, match="no candidates"):
        GeminiLLMProvider(api_key=DUMMY_KEY).generate("p")


def test_malformed_empty_text(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(_candidates("   ")))
    with pytest.raises(MalformedLLMResponse, match="empty"):
        GeminiLLMProvider(api_key=DUMMY_KEY).generate("p")


def test_malformed_missing_parts(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: FakeResponse({"candidates": [{"content": {}}]})
    )
    with pytest.raises(MalformedLLMResponse, match="parts"):
        GeminiLLMProvider(api_key=DUMMY_KEY).generate("p")


def test_http_error_is_sanitized(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(status_code=429))
    with pytest.raises(LLMProviderError) as excinfo:
        GeminiLLMProvider(api_key=DUMMY_KEY).generate("p")
    assert "HTTP 429" in str(excinfo.value)
    assert DUMMY_KEY not in str(excinfo.value)


def test_timeout_maps_to_typed_error(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(api_key=DUMMY_KEY, timeout_seconds=3.0)
    with pytest.raises(LLMProviderTimeout, match="timed out after 3.0s"):
        provider.generate("p")


def test_transport_error_is_sanitized(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LLMProviderError, match="ConnectError"):
        GeminiLLMProvider(api_key=DUMMY_KEY).generate("p")


def test_constructor_rejects_missing_key():
    with pytest.raises(LLMProviderError, match="missing"):
        GeminiLLMProvider(api_key="")


def test_factory_raises_without_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", None)
    with pytest.raises(LLMProviderNotConfigured, match="GEMINI_API_KEY"):
        get_llm_provider()


def test_factory_returns_gemini_provider_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", DUMMY_KEY)
    monkeypatch.setattr(settings, "gemini_llm_model", "gemini-2.5-flash")
    provider = get_llm_provider()
    assert isinstance(provider, GeminiLLMProvider)
    assert provider.model == "gemini-2.5-flash"


def test_factory_raises_without_agentrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "agentrouter")
    monkeypatch.setattr(settings, "agentic_api_key", None)
    monkeypatch.setattr(settings, "agentrouter_base_url", "https://gw.example.com/v1")
    with pytest.raises(LLMProviderNotConfigured, match="AGENTIC_API_KEY"):
        get_llm_provider()


def test_factory_raises_without_agentrouter_base_url(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "agentrouter")
    monkeypatch.setattr(settings, "agentic_api_key", DUMMY_KEY)
    monkeypatch.setattr(settings, "agentrouter_base_url", None)
    with pytest.raises(LLMProviderNotConfigured, match="AGENTROUTER_BASE_URL"):
        get_llm_provider()


def test_factory_returns_agentrouter_provider_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "agentrouter")
    monkeypatch.setattr(settings, "agentic_api_key", DUMMY_KEY)
    monkeypatch.setattr(settings, "agentrouter_base_url", "https://gw.example.com/v1/")
    monkeypatch.setattr(settings, "agentrouter_model", "deepseek-v4-flash")
    provider = get_llm_provider()
    assert isinstance(provider, AgentRouterLLMProvider)
    assert provider.model == "deepseek-v4-flash"


def test_factory_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "watson")
    with pytest.raises(LLMProviderNotConfigured, match="LLM_PROVIDER"):
        get_llm_provider()


# ── AgentRouter (OpenAI-compatible) provider ─────────────────────────────


def _chat_choices(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def test_agentrouter_generate_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse(_chat_choices("  Consistency beats intensity.  "))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = AgentRouterLLMProvider(
        api_key=DUMMY_KEY, base_url="https://gw.example.com/v1",
        model="deepseek-v4-flash", timeout_seconds=7.0,
    )

    assert provider.generate("prompt text") == "Consistency beats intensity."
    assert captured["url"] == "https://gw.example.com/v1/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["json"]["messages"] == [
        {"role": "user", "content": "prompt text"}
    ]
    assert captured["headers"]["Authorization"] == f"Bearer {DUMMY_KEY}"
    # agentrouter.org rejects non-claude-cli User-Agents (live-discovered
    # 2026-09-06) — the gateway must see this exact header to route the call.
    assert captured["headers"]["User-Agent"] == (
        "claude-cli/1.0.0 (external, cli)"
    )
    assert DUMMY_KEY not in captured["url"]
    assert captured["timeout"] == 7.0


def test_agentrouter_satisfies_the_protocol(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(_chat_choices("ok")))
    assert isinstance(
        AgentRouterLLMProvider(
            api_key=DUMMY_KEY, base_url="https://gw.example.com/v1"
        ),
        LLMProvider,
    )


def test_agentrouter_http_error_is_sanitized(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: FakeResponse(status_code=429)
    )
    with pytest.raises(LLMProviderError) as excinfo:
        AgentRouterLLMProvider(
            api_key=DUMMY_KEY, base_url="https://gw.example.com/v1"
        ).generate("p")
    assert "HTTP 429" in str(excinfo.value)
    assert DUMMY_KEY not in str(excinfo.value)


def test_agentrouter_malformed_no_choices(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse({"choices": []}))
    with pytest.raises(MalformedLLMResponse, match="no choices"):
        AgentRouterLLMProvider(
            api_key=DUMMY_KEY, base_url="https://gw.example.com/v1"
        ).generate("p")


def test_agentrouter_malformed_empty_content(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: FakeResponse(_chat_choices("   "))
    )
    with pytest.raises(MalformedLLMResponse, match="empty"):
        AgentRouterLLMProvider(
            api_key=DUMMY_KEY, base_url="https://gw.example.com/v1"
        ).generate("p")


def test_agentrouter_timeout_maps_to_typed_error(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = AgentRouterLLMProvider(
        api_key=DUMMY_KEY, base_url="https://gw.example.com/v1", timeout_seconds=3.0
    )
    with pytest.raises(LLMProviderTimeout, match="timed out after 3.0s"):
        provider.generate("p")


def test_agentrouter_constructor_rejects_missing_key_or_base_url():
    with pytest.raises(LLMProviderError, match="AGENTIC_API_KEY"):
        AgentRouterLLMProvider(api_key="", base_url="https://gw.example.com/v1")
    with pytest.raises(LLMProviderError, match="AGENTROUTER_BASE_URL"):
        AgentRouterLLMProvider(api_key=DUMMY_KEY, base_url="")
