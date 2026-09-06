"""Coach API (Phase 4C.2).

ONE endpoint: ``GET /api/v1/coach`` — grounded AI coaching for the
current (dev) user. Providers come from the module factories (Gemini when
configured); every upstream failure maps to an honest HTTP error, never a
silent 200.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.dependencies import get_current_user, get_db
from app.modules.coach.cache import coach_cache
from app.modules.coach.llm import (
    LLMProviderError,
    LLMProviderNotConfigured,
    LLMProviderTimeout,
    MalformedLLMResponse,
    get_llm_provider,
)
from app.modules.coach.schemas import CoachResponse
from app.modules.coach.service import CoachValidationError, generate_coaching
from app.modules.rag.providers import (
    EmbeddingProviderError,
    EmbeddingProviderNotConfigured,
    EmbeddingProviderTimeout,
    get_embedding_provider,
)

router = APIRouter()


@router.get("", response_model=CoachResponse)
def coach_endpoint(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> CoachResponse:
    """Grounded coaching: real user context → retrieval → LLM.

    Error mapping (upstream failures are never HTTP 200):
    - provider not configured (missing key)   → 503
    - embedding / LLM timeout                 → 504
    - provider transport/API error, malformed
      LLM output, failed response validation  → 502
    """
    user_id = uuid.UUID(current_user["id"])
    try:
        return generate_coaching(
            db,
            user_id=user_id,
            embedding_provider=get_embedding_provider(),
            llm_provider=get_llm_provider(),
            cache=coach_cache,
        )
    except (EmbeddingProviderNotConfigured, LLMProviderNotConfigured) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EmbeddingProviderTimeout, LLMProviderTimeout) as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (
        EmbeddingProviderError,
        LLMProviderError,
        MalformedLLMResponse,
        CoachValidationError,
    ) as exc:
        # MalformedLLMResponse is an LLMProviderError subclass; listed for
        # readability. None of these messages contain credentials.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
