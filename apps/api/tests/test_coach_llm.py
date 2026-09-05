"""Phase 4C.2 Gemini LLM-provider tests (httpx mocked — zero API calls)."""
import httpx
import pytest

from app.core.config import settings
from app.modules.coach.llm import (
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
    monkeypatch.setattr(settings, "gemini_api_key", None)
    with pytest.raises(LLMProviderNotConfigured, match="GEMINI_API_KEY"):
        get_llm_provider()


def test_factory_returns_gemini_provider_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", DUMMY_KEY)
    monkeypatch.setattr(settings, "gemini_llm_model", "gemini-2.5-flash")
    provider = get_llm_provider()
    assert isinstance(provider, GeminiLLMProvider)
    assert provider.model == "gemini-2.5-flash"
