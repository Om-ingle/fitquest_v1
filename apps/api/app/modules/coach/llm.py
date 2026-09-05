"""LLM provider layer (Phase 4C.2, SRS §14).

``LLMProvider`` is the vendor-neutral interface the coach service talks
to; ``GeminiLLMProvider`` is the single real implementation (one vendor
for embeddings + LLM — see app/modules/rag/README.md for the rationale).
Plain REST via httpx, no vendor SDK.

The API key travels in the ``x-goog-api-key`` header and never appears in
errors, logs, or responses. No test in this repository performs a real
API call — the coach service and the API tests inject fakes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from app.core.config import settings
from app.modules.rag.providers import GEMINI_API_BASE


@runtime_checkable
class LLMProvider(Protocol):
    """Anything that turns a prompt into generated text.

    Contract:
    - ``generate(prompt)`` returns the model's text output (stripped).
    - Implementations must not fabricate output on failure — they raise.
    """

    def generate(self, prompt: str) -> str: ...


class LLMProviderError(RuntimeError):
    """The LLM provider failed (transport, API, or malformed output).

    The message is sanitized: it never contains the API key.
    """


class LLMProviderTimeout(LLMProviderError):
    """The LLM API call exceeded the configured timeout."""


class LLMProviderNotConfigured(RuntimeError):
    """Raised when the LLM is needed but no provider is configured."""


class MalformedLLMResponse(LLMProviderError):
    """The model answered, but the response has no usable text (e.g. empty
    candidates or blocked output). Treated as an upstream failure."""


class GeminiLLMProvider:
    """Real LLM provider: Gemini ``generateContent`` (REST)."""

    def __init__(
        self,
        api_key: str,
        model: str = settings.gemini_llm_model,
        timeout_seconds: float = settings.llm_timeout_seconds,
    ):
        if not api_key:
            raise LLMProviderError("Gemini API key is missing (GEMINI_API_KEY)")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str) -> str:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 1024,
                # gemini-2.5-* models "think" by default and thinking tokens
                # count toward maxOutputTokens — with a small cap the visible
                # answer gets truncated mid-sentence (observed live). A short
                # coaching message needs no chain-of-thought, so disable it.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        data = self._post(f"/models/{self._model}:generateContent", json=payload)
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise MalformedLLMResponse(
                "Gemini LLM response has no candidates (possibly blocked or "
                "empty); model "
                f"{self._model}"
            )
        first = candidates[0]
        parts = first.get("content", {}).get("parts") if isinstance(first, dict) else None
        if not isinstance(parts, list):
            raise MalformedLLMResponse("Gemini LLM response has no content parts")
        text = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        ).strip()
        if not text:
            raise MalformedLLMResponse("Gemini LLM response text is empty")
        return text

    def _post(self, path: str, json: dict) -> dict:
        try:
            response = httpx.post(
                f"{GEMINI_API_BASE}{path}",
                json=json,
                headers={"x-goog-api-key": self._api_key},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeout(
                f"Gemini LLM request timed out after "
                f"{self._timeout_seconds}s (model {self._model})"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"Gemini LLM request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise LLMProviderError(
                f"Gemini LLM API returned HTTP {response.status_code} "
                f"(model {self._model})"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise LLMProviderError("Gemini LLM API returned a non-JSON body") from exc


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider, or fail loudly."""
    if not settings.gemini_api_key:
        raise LLMProviderNotConfigured(
            "No LLM provider is configured: set GEMINI_API_KEY in the "
            "backend environment/.env (backend-only; never in Android)."
        )
    return GeminiLLMProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
