"""Grounded AI coach service (Phase 4C.2, SRS §13/§14).

Orchestrates the full grounded-coaching flow, independent of HTTP:

    1. Build the user's REAL Phase 4A FitnessContext (server data only).
    2. Run the deterministic recommendation engine (unchanged — it stays
       the authority for recommendation logic; the LLM only explains).
    3. Build a topical retrieval query and embed it (injected provider).
    4. Retrieve knowledge chunks above the similarity threshold.
    5. Build the grounded prompt (context / knowledge / instructions).
    6. Call the LLM (injected provider).
    7. Validate the response and return the structured coach result.

Fallback behavior (deliberate choice, documented in the module README):
when retrieval returns NOTHING above the threshold, the service still
produces a response, but the prompt explicitly tells the model no
knowledge was retrieved and the result is flagged ``grounded=False``.
It is therefore never presented as RAG-grounded coaching (SRS §13.4).

Provider failures propagate as typed exceptions (EmbeddingProviderError,
EmbeddingProviderTimeout, LLMProviderError, LLMProviderTimeout,
MalformedLLMResponse) — the router maps them to HTTP errors; nothing is
silently turned into a success.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from sqlmodel import Session

from app.core.config import settings
from app.modules.coach.cache import CoachCache, context_fingerprint
from app.modules.coach.llm import LLMProvider
from app.modules.coach.prompt import build_coaching_prompt, build_retrieval_query
from app.modules.coach.schemas import ChunkSummary, CoachResponse, RetrievalInfo
from app.modules.rag.providers import EmbeddingProvider
from app.modules.rag.schemas import RetrievedChunk
from app.modules.rag.service import retrieve_chunks
from app.modules.recommendations.schemas import FitnessContext, Recommendation
from app.modules.recommendations.service import build_fitness_context, recommend

# Hard cap on the accepted LLM message length — a runaway response is a
# malformed response, not coaching.
MAX_MESSAGE_CHARS = 4000


class CoachValidationError(RuntimeError):
    """The LLM response failed post-generation validation."""


def generate_coaching(
    db: Session,
    *,
    user_id: uuid.UUID,
    embedding_provider: EmbeddingProvider,
    llm_provider: LLMProvider,
    top_k: Optional[int] = None,
    min_similarity: Optional[float] = None,
    cache: Optional[CoachCache] = None,
) -> CoachResponse:
    """Run the full grounded coaching flow for one user.

    ``cache`` (Fix E) is optional so direct-service tests can opt out. When
    provided and the user's freshly-built context fingerprint matches a
    stored generation, that stored response is returned with ``cached=True``
    and NO LLM/RAG work happens. The context is rebuilt fresh on EVERY call
    — a cache hit is decided against current data, never against a stored
    stale context. Failures are never cached: only a validated response is
    stored, so a Retry after an error always reaches the LLM.
    """
    if top_k is None:
        top_k = settings.coach_top_k
    if min_similarity is None:
        min_similarity = settings.rag_similarity_threshold

    # 1. Real context — built fresh every call (never a stored value).
    context: FitnessContext = build_fitness_context(db, user_id)
    fingerprint = context_fingerprint(context)

    # 2. Fix E: same user + same context fingerprint → serve the stored
    #    generation unchanged (no recommendation/embedding/LLM work at all).
    if cache is not None:
        cached = cache.get_cached(user_id, fingerprint)
        if cached is not None:
            return cached.model_copy(update={"cached": True})

    # 3. Deterministic recommendation (Phase 4A, reused).
    recommendation: Recommendation = recommend(context)

    # 4. Topical query, embedded by the injected provider.
    query_text = build_retrieval_query(context, recommendation)
    query_embedding = embedding_provider.embed_texts([query_text])[0]

    # 5. Knowledge above the similarity threshold (never unrelated chunks).
    chunks: list[RetrievedChunk] = retrieve_chunks(
        db,
        query_embedding=query_embedding,
        top_k=top_k,
        min_similarity=min_similarity,
    )

    # 6-7. Grounded prompt, then the LLM.
    prompt = build_coaching_prompt(context, recommendation, chunks)
    message = llm_provider.generate(prompt)

    # 8. Validate before returning/storing.
    message = message.strip()
    if not message:
        raise CoachValidationError("LLM returned an empty coaching message")
    if len(message) > MAX_MESSAGE_CHARS:
        raise CoachValidationError(
            f"LLM coaching message exceeds {MAX_MESSAGE_CHARS} characters"
        )

    response = CoachResponse(
        generated_at=datetime.datetime.utcnow(),
        message=message,
        grounded=bool(chunks),
        context=context,
        recommendation=recommendation,
        retrieval=RetrievalInfo(
            query_text=query_text,
            top_k=top_k,
            min_similarity=min_similarity,
            retrieved_count=len(chunks),
            chunks=[
                ChunkSummary(
                    document_title=chunk.document_title,
                    document_source=chunk.document_source,
                    chunk_index=chunk.chunk_index,
                    similarity=chunk.similarity,
                )
                for chunk in chunks
            ],
        ),
        context_fingerprint=fingerprint,
    )

    # Only a fully validated response is cached — an error above never
    # leaves a stale entry behind.
    if cache is not None:
        cache.store(user_id, fingerprint, response)
    return response
