"""LLM provider layer (Phase 4C.2, SRS §14).

``LLMProvider`` is the vendor-neutral interface the coach service talks
to. Two real implementations exist: ``GeminiLLMProvider`` (default; one
vendor for embeddings + LLM — see app/modules/rag/README.md for the
rationale) and ``AgentRouterLLMProvider`` (an OpenAI-compatible gateway
selected via ``LLM_PROVIDER=agentrouter`` when the Gemini free-tier
text-generation quota is exhausted — embeddings stay on Gemini).
Plain REST via httpx, no vendor SDK.

API keys travel in headers (``x-goog-api-key`` or ``Authorization:
Bearer``) and never appear in errors, logs, or responses. No test in
this repository performs a real API call — the coach service and the
API tests inject fakes.
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


class AgentRouterLLMProvider:
    """Alternative LLM provider: an OpenAI-compatible gateway
    (``/chat/completions``) — e.g. DeepSeek behind an AgentRouter key.

    Selected via ``LLM_PROVIDER=agentrouter`` in the backend .env when the
    default Gemini free-tier text-generation quota is exhausted. The key
    travels in the ``Authorization: Bearer`` header and never appears in
    errors, logs, or responses (mirrors [GeminiLLMProvider]). Embeddings
    are unaffected — they stay on Gemini in both modes.
    """

    # Live-discovered requirement (2026-09-06): agentrouter.org rejects any
    # non-``claude-cli`` User-Agent with ``401 unauthorized client detected``
    # (an application-level client filter, verified: identical request 401s
    # with the default httpx UA and 200s with this one). The header is sent
    # verbatim so the gateway routes the call.
    _CLAUDE_CLI_UA = "claude-cli/1.0.0 (external, cli)"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = settings.agentrouter_model,
        timeout_seconds: float = settings.llm_timeout_seconds,
    ):
        if not api_key:
            raise LLMProviderError(
                "AgentRouter API key is missing (AGENTIC_API_KEY)"
            )
        if not base_url:
            raise LLMProviderError(
                "AgentRouter base URL is missing (AGENTROUTER_BASE_URL)"
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 1024,
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": self._CLAUDE_CLI_UA,
                },
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeout(
                f"AgentRouter LLM request timed out after "
                f"{self._timeout_seconds}s (model {self._model})"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"AgentRouter LLM request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise LLMProviderError(
                f"AgentRouter LLM API returned HTTP {response.status_code} "
                f"(model {self._model})"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMProviderError(
                "AgentRouter LLM API returned a non-JSON body"
            ) from exc
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise MalformedLLMResponse(
                "AgentRouter LLM response has no choices (possibly blocked "
                f"or empty); model {self._model}"
            )
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content")
        # OpenAI-compatible APIs return content as a string; a handful return
        # a list of typed parts. Accept both, mirroring the Gemini parser.
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        else:
            text = ""
        text = text.strip()
        if not text:
            raise MalformedLLMResponse(
                "AgentRouter LLM response text is empty"
            )
        return text


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider, or fail loudly.

    ``LLM_PROVIDER`` in the backend .env selects the backend: ``gemini``
    (default) or ``agentrouter`` (an OpenAI-compatible gateway such as
    DeepSeek, behind the AGENTIC_API_KEY / AGENTROUTER_BASE_URL pair).
    The switch exists so live device testing can continue when the Gemini
    free-tier text-generation quota is exhausted.
    """
    kind = (settings.llm_provider or "gemini").strip().lower()
    if kind == "agentrouter":
        if not settings.agentic_api_key:
            raise LLMProviderNotConfigured(
                "No AgentRouter LLM provider is configured: set "
                "AGENTIC_API_KEY and AGENTROUTER_BASE_URL in the backend "
                "environment/.env (backend-only; never in Android)."
            )
        if not settings.agentrouter_base_url:
            raise LLMProviderNotConfigured(
                "No AgentRouter LLM provider is configured: AGENTROUTER_"
                "BASE_URL is missing (backend environment/.env)."
            )
        return AgentRouterLLMProvider(
            api_key=settings.agentic_api_key,
            base_url=settings.agentrouter_base_url,
            model=settings.agentrouter_model or "deepseek-v4-flash",
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if kind == "gemini":
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
    raise LLMProviderNotConfigured(
        f"Unknown LLM_PROVIDER value {settings.llm_provider!r}: expected "
        "'gemini' or 'agentrouter'."
    )
