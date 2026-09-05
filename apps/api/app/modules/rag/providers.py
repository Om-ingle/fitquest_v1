"""Embedding-provider abstraction (Phases 4C.1 + 4C.2).

SRS §14: the application must not depend directly on one AI vendor. The
retrieval/ingestion services therefore only ever talk to the
``EmbeddingProvider`` protocol below; the concrete provider is injected.

Phase 4C.2 adds ONE real provider: Google Gemini ``batchEmbedContents``
over plain REST (httpx — no vendor SDK dependency). Gemini is the single
vendor for BOTH embeddings and the LLM (SRS §14 names Gemini/OpenRouter;
Gemini alone offers embeddings + generation behind one key, which suits a
student project; the protocol keeps the vendor swappable).

The API key is passed via the ``x-goog-api-key`` HEADER (never the URL
query string) and is never included in any error message, log line, or
exception raised here.
"""

from __future__ import annotations

import math
from typing import Protocol, Sequence, runtime_checkable

import httpx

from app.core.config import settings
from app.modules.rag.constants import EMBEDDING_DIMENSION

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Anything that can turn texts into fixed-width vectors.

    Contract:
    - ``dimension`` always matches the width of every returned vector and
      equals the persistence-layer constant ``EMBEDDING_DIMENSION``.
    - ``embed_texts`` returns exactly one vector per input text, in input
      order.
    - Implementations must be deterministic for repeated calls where the
      underlying model allows it, and must never fabricate vectors (no
      random "AI-ish" output).
    """

    @property
    def dimension(self) -> int: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingProviderError(RuntimeError):
    """The embedding provider failed (transport, API, or malformed output).

    The message is sanitized: it never contains the API key.
    """


class EmbeddingProviderTimeout(EmbeddingProviderError):
    """The embedding API call exceeded the configured timeout."""


class EmbeddingProviderNotConfigured(RuntimeError):
    """Raised when an embedding is needed but no provider is configured.

    Honest failure beats pretending embeddings exist.
    """


class GeminiEmbeddingProvider:
    """Real embedding provider: Gemini ``batchEmbedContents`` (REST).

    Requests ``outputDimensionality = EMBEDDING_DIMENSION`` (1536) so the
    vectors fit the Phase 4C.1 schema/migration without any migration
    churn, and validates the returned width at runtime — a model or API
    change that returns a different width fails loudly here instead of
    corrupting ``ragchunk.embedding`` rows.
    """

    def __init__(
        self,
        api_key: str,
        model: str = settings.gemini_embedding_model,
        output_dimension: int = EMBEDDING_DIMENSION,
        timeout_seconds: float = settings.embedding_timeout_seconds,
    ):
        if not api_key:
            # Defensive: the factory checks this too, but a provider must
            # never silently run with an empty key.
            raise EmbeddingProviderError("Gemini API key is missing (GEMINI_API_KEY)")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self.dimension = output_dimension

    @property
    def model(self) -> str:
        return self._model

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        requests = [
            {
                "model": f"models/{self._model}",
                "content": {"parts": [{"text": text}]},
                "outputDimensionality": self.dimension,
            }
            for text in texts
        ]
        response = self._post(
            f"/models/{self._model}:batchEmbedContents",
            json={"requests": requests},
        )
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingProviderError(
                "Gemini embedding response malformed: expected one embedding "
                f"per input text ({len(texts)}), got "
                f"{len(embeddings) if isinstance(embeddings, list) else 'non-list'}"
            )
        vectors: list[list[float]] = []
        for i, item in enumerate(embeddings):
            values = item.get("values") if isinstance(item, dict) else None
            if not isinstance(values, list) or not values:
                raise EmbeddingProviderError(
                    f"Gemini embedding response malformed: embedding #{i} "
                    "has no 'values' list"
                )
            try:
                vector = [float(x) for x in values]
            except (TypeError, ValueError) as exc:
                raise EmbeddingProviderError(
                    f"Gemini embedding response malformed: embedding #{i} "
                    "contains non-numeric values"
                ) from exc
            if len(vector) != self.dimension:
                raise EmbeddingProviderError(
                    f"Gemini embedding model '{self._model}' returned width "
                    f"{len(vector)}, expected {self.dimension}. The model or "
                    "outputDimensionality configuration does not match the "
                    "persisted schema (ragchunk.embedding)."
                )
            if not all(math.isfinite(x) for x in vector):
                raise EmbeddingProviderError(
                    f"Gemini embedding response malformed: embedding #{i} "
                    "contains non-finite values"
                )
            vectors.append(vector)
        return vectors

    def _post(self, path: str, json: dict) -> dict:
        """POST to the Gemini REST API. Raises sanitized errors only."""
        try:
            response = httpx.post(
                f"{GEMINI_API_BASE}{path}",
                json=json,
                headers={"x-goog-api-key": self._api_key},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingProviderTimeout(
                f"Gemini embedding request timed out after "
                f"{self._timeout_seconds}s (model {self._model})"
            ) from exc
        except httpx.HTTPError as exc:
            # httpx errors carry no credentials (auth is a header), but keep
            # the message to exception-class + generic cause anyway.
            raise EmbeddingProviderError(
                f"Gemini embedding request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            # Truncated, non-sensitive status line only — never the request
            # body (which contains the key only in headers, but be strict).
            raise EmbeddingProviderError(
                f"Gemini embedding API returned HTTP {response.status_code} "
                f"(model {self._model})"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise EmbeddingProviderError(
                "Gemini embedding API returned a non-JSON body"
            ) from exc


def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured provider, or fail loudly.

    The provider is Gemini when ``GEMINI_API_KEY`` is set (backend .env /
    environment only). With no key, embedding-dependent features fail with
    ``EmbeddingProviderNotConfigured`` rather than fabricating vectors.
    """
    if not settings.gemini_api_key:
        raise EmbeddingProviderNotConfigured(
            "No embedding provider is configured: set GEMINI_API_KEY in the "
            "backend environment/.env (backend-only; never in Android)."
        )
    return GeminiEmbeddingProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_embedding_model,
        output_dimension=EMBEDDING_DIMENSION,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
