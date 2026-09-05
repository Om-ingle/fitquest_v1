"""Coach response schemas (Phase 4C.2).

The coaching endpoint returns the LLM message plus everything needed to
understand WHERE it came from: the real Phase 4A context and
recommendation it was grounded in, and retrieval metadata for
testing/debugging. The raw prompt and provider credentials are never
exposed.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.modules.recommendations.schemas import FitnessContext, Recommendation


class ChunkSummary(BaseModel):
    """Debug/testing summary of one retrieved chunk (content excluded to
    keep the payload lean; the full chunk lives in the knowledge base)."""

    document_title: str
    document_source: str
    chunk_index: int
    similarity: float


class RetrievalInfo(BaseModel):
    """How the knowledge was retrieved for this coaching response."""

    query_text: str
    top_k: int
    min_similarity: float
    retrieved_count: int
    chunks: list[ChunkSummary]


class CoachResponse(BaseModel):
    """GET /api/v1/coach payload.

    ``grounded`` is True only when the LLM was given retrieved knowledge;
    when retrieval found nothing above the threshold the response is a
    flagged general-guidance fallback (see coach/service.py).
    """

    generated_at: datetime
    message: str
    grounded: bool
    context: FitnessContext
    recommendation: Recommendation
    retrieval: RetrievalInfo
