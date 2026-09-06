"""MANUAL live coach smoke evaluation (Phase 4C.3A) — NOT run by pytest.

Runs the REAL coaching pipeline (Gemini embeddings + gemini-2.5-flash LLM +
live Supabase/pgvector retrieval) for a small FIXED set of cases:

- 5 SYNTHETIC FitnessContext scenarios (cold start / lapsed / territory
  defense / consistent / maintain). These contexts are constructed in
  memory and are NOT real user data — they exist so each recommendation
  branch can be observed live without mutating anyone's database rows.
- 1 REAL case for the dev user, through the actual service entry point
  (coach.service.generate_coaching), exactly as GET /api/v1/coach runs it.

Total API spend per run: 2 embedding batch calls + 6 LLM calls. Small on
purpose — this is a smoke evaluation, not a sweep.

Usage (from apps/api, with GEMINI_API_KEY and DATABASE_URL in .env):

    python tools/evaluate_live_coach.py

The script is READ-ONLY against the database. It never prints the API key,
the raw prompt, or any other secret, and it persists nothing.

Qualitative, honestly: the observer (you) judges relevance / grounding /
personalization / coherence / non-copying by reading the messages. No
subjective quality is converted into a fake precise score.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Make `app` importable when run as a plain script from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main  # noqa: E402,F401  (registers every SQLModel mapper — the
# real-user case touches the User mapper, whose relationships resolve only
# when all models are imported)

from sqlmodel import Session  # noqa: E402

from app.api.dependencies import DEV_USER_ID  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.modules.coach.llm import get_llm_provider  # noqa: E402
from app.modules.coach.prompt import build_coaching_prompt, build_retrieval_query  # noqa: E402
from app.modules.coach.service import MAX_MESSAGE_CHARS, generate_coaching  # noqa: E402
from app.modules.rag.providers import get_embedding_provider  # noqa: E402
from app.modules.rag.service import retrieve_chunks  # noqa: E402
from app.modules.recommendations.schemas import FitnessContext  # noqa: E402
from app.modules.recommendations.service import recommend  # noqa: E402

NOW = datetime.utcnow()


def _scenario(
    label: str, note: str, **overrides
) -> tuple[str, str, FitnessContext]:
    defaults = dict(
        user_id=uuid.UUID(DEV_USER_ID),
        total_lifetime_steps=0,
        hexes_owned=0,
        recent_captures_7d=0,
        last_capture_at=None,
        total_defense_steps=0,
    )
    defaults.update(overrides)
    return label, note, FitnessContext(**defaults)


SYNTHETIC_SCENARIOS = [
    _scenario(
        "cold-start", "brand new player, zero footprint",
        total_lifetime_steps=0, hexes_owned=0, recent_captures_7d=0,
        last_capture_at=None, total_defense_steps=0,
    ),
    _scenario(
        "lapsed", "has history, last capture 5 days ago",
        total_lifetime_steps=8000, hexes_owned=1, recent_captures_7d=1,
        last_capture_at=NOW - timedelta(days=5), total_defense_steps=400,
    ),
    _scenario(
        "territory-defense", "owns hexes, nothing captured this week",
        total_lifetime_steps=12000, hexes_owned=3, recent_captures_7d=0,
        last_capture_at=NOW - timedelta(hours=36), total_defense_steps=900,
    ),
    _scenario(
        "consistent", "capturing all week",
        total_lifetime_steps=50000, hexes_owned=4, recent_captures_7d=4,
        last_capture_at=NOW, total_defense_steps=1200,
    ),
    _scenario(
        "maintain", "active at a moderate volume",
        total_lifetime_steps=20000, hexes_owned=1, recent_captures_7d=1,
        last_capture_at=NOW - timedelta(days=1), total_defense_steps=150,
    ),
]


def _print_chunks(chunks) -> None:
    if not chunks:
        print("  retrieval : (nothing passed the threshold → grounded=false)")
        return
    for chunk in chunks:
        print(
            f"  retrieval : {chunk.similarity:.4f}  {chunk.document_title} "
            f"({chunk.document_source}, chunk {chunk.chunk_index})"
        )


def _validate_message(message: str) -> str:
    stripped = message.strip()
    if not stripped:
        raise SystemExit("EVAL FAILED: LLM returned an empty message")
    if len(stripped) > MAX_MESSAGE_CHARS:
        raise SystemExit("EVAL FAILED: LLM message exceeded the length cap")
    return stripped


def run_synthetic_scenarios(session, embedding_provider, llm_provider) -> None:
    contexts = []
    print("=" * 78)
    print("PART 1 — SYNTHETIC EVALUATION SCENARIOS (constructed contexts,")
    print("NOT real user data; the recommendation engine + retrieval + LLM")
    print("are all real).")
    print("=" * 78)
    for label, note, context in SYNTHETIC_SCENARIOS:
        recommendation = recommend(context)
        query_text = build_retrieval_query(context, recommendation)
        contexts.append((label, note, context, recommendation, query_text))

    # ONE batched embedding call for all five retrieval queries.
    embeddings = embedding_provider.embed_texts(
        [query_text for *_rest, query_text in contexts]
    )

    for (label, note, context, recommendation, query_text), embedding in zip(
        contexts, embeddings
    ):
        print(f"\n[{label}] {note}")
        print(
            f"  recommendation: {recommendation.type} — {recommendation.title} "
            f"({recommendation.reason_code})"
        )
        chunks = retrieve_chunks(
            session,
            query_embedding=embedding,
            top_k=settings.coach_top_k,
            min_similarity=settings.rag_similarity_threshold,
        )
        _print_chunks(chunks)
        prompt = build_coaching_prompt(context, recommendation, chunks)
        message = _validate_message(llm_provider.generate(prompt))
        print(f"  grounded : {bool(chunks)}")
        print(f"  message  : {message}")


def run_real_dev_user_case(session, embedding_provider, llm_provider) -> None:
    print()
    print("=" * 78)
    print("PART 2 — REAL dev-user case through the actual service entry")
    print("point (exactly what GET /api/v1/coach runs; read-only).")
    print("=" * 78)
    result = generate_coaching(
        session,
        user_id=uuid.UUID(DEV_USER_ID),
        embedding_provider=embedding_provider,
        llm_provider=llm_provider,
    )
    print(f"  recommendation: {result.recommendation.type} "
          f"({result.recommendation.reason_code})")
    _print_chunks(result.retrieval.chunks)
    print(f"  grounded : {result.grounded}")
    print(f"  message  : {result.message}")


def main() -> int:
    print("=" * 78)
    print("FitQuest LIVE coach smoke evaluation — MANUAL tool (4C.3A)")
    print("6 LLM calls + 2 embedding batch calls total. Read-only.")
    print("=" * 78)
    print(f"embedding model : {settings.gemini_embedding_model}")
    print(f"llm model       : {settings.gemini_llm_model}")
    print(
        f"configuration   : top_k={settings.coach_top_k}, "
        f"min_similarity={settings.rag_similarity_threshold}"
    )

    embedding_provider = get_embedding_provider()  # fails loudly, no key printed
    llm_provider = get_llm_provider()

    # --real-only skips the synthetic scenarios (e.g. to re-run just the
    # real-user case after a partial failure without re-spending the 5
    # scenario LLM calls).
    real_only = "--real-only" in sys.argv

    with Session(engine) as session:
        if not real_only:
            run_synthetic_scenarios(session, embedding_provider, llm_provider)
        run_real_dev_user_case(session, embedding_provider, llm_provider)

    print()
    print("=" * 78)
    print(
        "Qualitative review guide (judge by reading, no fake scores):\n"
        " - relevant: does the message address the scenario's situation?\n"
        " - grounded: does it reflect the retrieved knowledge (not invent)?\n"
        " - personalized: does it use the context's real situation?\n"
        " - coherent: complete sentences, no truncation mid-thought?\n"
        " - not copying: synthesized, not a verbatim chunk echo?"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
