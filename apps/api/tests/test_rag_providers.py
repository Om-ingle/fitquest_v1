"""Phase 4C.2 Gemini embedding-provider tests.

httpx.post is monkeypatched — NO real API call is ever made, and no test
reads a real API key (a dummy key value is used and asserted to NEVER
leak into error messages).
"""
import httpx
import pytest

from app.core.config import settings
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.rag.providers import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingProviderNotConfigured,
    EmbeddingProviderTimeout,
    GeminiEmbeddingProvider,
    get_embedding_provider,
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


def _values(width=EMBEDDING_DIMENSION, value=0.25):
    return [value] * width


def _batch_response(vectors):
    return {"embeddings": [{"values": v} for v in vectors]}


def _make_provider(**kwargs):
    kwargs.setdefault("api_key", DUMMY_KEY)
    return GeminiEmbeddingProvider(**kwargs)


def test_embed_texts_success_parses_and_validates(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse(_batch_response([_values(), _values(value=0.5)]))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = _make_provider(model="gemini-embedding-001", timeout_seconds=5.0)

    vectors = provider.embed_texts(["first text", "second text"])

    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIMENSION for v in vectors)
    assert vectors[0][0] == pytest.approx(0.25)
    assert vectors[1][0] == pytest.approx(0.5)    # Request shape: batch embed, one request per text, in order, with the
    # pinned output dimension.
    assert "batchEmbedContents" in captured["url"]
    requests = captured["json"]["requests"]
    assert [r["content"]["parts"][0]["text"] for r in requests] == [
        "first text",
        "second text",
    ]
    assert all(r["outputDimensionality"] == EMBEDDING_DIMENSION for r in requests)
    # The key travels in a header, never in the URL.
    assert DUMMY_KEY not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == DUMMY_KEY
    assert captured["timeout"] == 5.0


def test_embed_texts_empty_input_makes_no_call(monkeypatch):
    called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: called.append(k))
    assert _make_provider().embed_texts([]) == []
    assert called == []


def test_provider_satisfies_the_protocol():
    assert isinstance(_make_provider(), EmbeddingProvider)


def test_malformed_response_wrong_count(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: FakeResponse(_batch_response([_values()]))
    )
    with pytest.raises(EmbeddingProviderError, match="one embedding per input"):
        _make_provider().embed_texts(["a", "b"])


def test_malformed_response_wrong_width(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: FakeResponse(_batch_response([_values(7)]))
    )
    with pytest.raises(EmbeddingProviderError, match="width 7"):
        _make_provider().embed_texts(["a"])


@pytest.mark.parametrize("bad_values", [None, [], ["x", "y"], [0.1, None]])
def test_malformed_response_bad_values(monkeypatch, bad_values):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: FakeResponse({"embeddings": [{"values": bad_values}]}),
    )
    with pytest.raises(EmbeddingProviderError, match="malformed"):
        _make_provider().embed_texts(["a"])


def test_malformed_response_non_finite(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: FakeResponse({"embeddings": [{"values": [float("inf")] * EMBEDDING_DIMENSION}]}),
    )
    with pytest.raises(EmbeddingProviderError, match="non-finite"):
        _make_provider().embed_texts(["a"])


def test_http_error_status_is_sanitized(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(status_code=500))
    provider = _make_provider()
    with pytest.raises(EmbeddingProviderError) as excinfo:
        provider.embed_texts(["a"])
    assert "HTTP 500" in str(excinfo.value)
    assert DUMMY_KEY not in str(excinfo.value)


def test_non_json_body(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(payload=None))
    with pytest.raises(EmbeddingProviderError, match="non-JSON"):
        _make_provider().embed_texts(["a"])


def test_timeout_maps_to_typed_error(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.TimeoutException("connection timed out")

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = _make_provider(timeout_seconds=1.0)
    with pytest.raises(EmbeddingProviderTimeout, match="timed out after 1.0s"):
        provider.embed_texts(["a"])
    # Timeout is a provider error (single except in callers is fine).
    assert isinstance(EmbeddingProviderTimeout("x"), EmbeddingProviderError)


def test_transport_error_is_sanitized(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(EmbeddingProviderError, match="ConnectError") as excinfo:
        _make_provider().embed_texts(["a"])
    assert DUMMY_KEY not in str(excinfo.value)


def test_constructor_rejects_missing_key():
    with pytest.raises(EmbeddingProviderError, match="missing"):
        GeminiEmbeddingProvider(api_key="")


def test_factory_raises_without_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    with pytest.raises(EmbeddingProviderNotConfigured, match="GEMINI_API_KEY"):
        get_embedding_provider()


def test_factory_returns_gemini_provider_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", DUMMY_KEY)
    monkeypatch.setattr(settings, "gemini_embedding_model", "gemini-embedding-001")
    provider = get_embedding_provider()
    assert isinstance(provider, GeminiEmbeddingProvider)
    assert provider.dimension == EMBEDDING_DIMENSION
    assert provider.model == "gemini-embedding-001"
