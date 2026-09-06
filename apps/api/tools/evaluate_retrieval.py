"""MANUAL live retrieval evaluation (Phase 4C.3A) — NOT run by pytest.

Runs the fixed evaluation query set (app/modules/rag/evaluation.py) against
the DATABASE_URL knowledge base using REAL Gemini embeddings (one batched
API call for the whole query set — a handful of embeddings, not a benchmark
sweep), then prints per-query results and Recall@k / hit-rate aggregates.

It also probes a few clearly off-topic queries WITHOUT a similarity
threshold, to show the raw scores unrelated text earns against the fitness
corpus — the evidence used to judge the RAG_SIMILARITY_THRESHOLD default.

Usage (from apps/api, with GEMINI_API_KEY and DATABASE_URL in .env):

    python tools/evaluate_retrieval.py

This is a small PROJECT-LEVEL SANITY EVALUATION, not a scientific
benchmark: the queries and expected documents were written by the project's
developers against the project's own 6-document corpus. Read the numbers as
"retrieval surfaces the documents we expect, for the queries we expect
users to ask" — nothing more.

Read-only: the script never writes to the database and never prints the
API key or any other secret.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `app` importable when run as a plain script from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.modules.rag.evaluation import (  # noqa: E402
    OFF_TOPIC_PROBE_QUERIES,
    run_retrieval_evaluation,
)
from app.modules.rag.providers import get_embedding_provider  # noqa: E402
from app.modules.rag.service import retrieve_chunks  # noqa: E402


def main() -> int:
    print("=" * 78)
    print("FitQuest RAG retrieval evaluation — MANUAL live tool (4C.3A)")
    print("Small project-level sanity evaluation, NOT a scientific benchmark.")
    print("=" * 78)

    # Fails loudly (with a clear message, never the key) when unconfigured.
    provider = get_embedding_provider()
    print(f"embedding model : {settings.gemini_embedding_model}")
    print(
        f"configuration   : top_k={settings.coach_top_k}, "
        f"min_similarity={settings.rag_similarity_threshold}"
    )
    print()

    with Session(engine) as session:
        report = run_retrieval_evaluation(
            session,
            provider=provider,
            top_k=settings.coach_top_k,
            min_similarity=settings.rag_similarity_threshold,
        )

        for result in report.results:
            expected = ", ".join(sorted(result.query.expected_documents))
            print(f"[{result.query.label}]")
            print(f"  query    : {result.query.query}")
            print(f"  expected : {expected}")
            if result.chunks:
                for chunk in result.chunks:
                    print(
                        f"  retrieved: {chunk.similarity:.4f}  "
                        f"{chunk.document_title} ({chunk.document_source}, "
                        f"chunk {chunk.chunk_index})"
                    )
            else:
                print("  retrieved: (nothing passed the threshold)")
            hit_mark = "HIT" if result.hit else "MISS"
            print(f"  recall@k : {result.recall:.2f}  [{hit_mark}]")
            print()

        print("-" * 78)
        print(
            f"AGGREGATE (k={report.top_k}, "
            f"threshold={report.min_similarity}): "
            f"mean Recall@k = {report.mean_recall_at_k:.2f}, "
            f"hit rate = {report.hit_rate:.2f} "
            f"({sum(1 for r in report.results if r.hit)}/{len(report.results)} queries)"
        )
        print()

        # ── Off-topic probe: raw scores with NO threshold ──────────────────
        print("-" * 78)
        print(
            "OFF-TOPIC PROBE — raw similarities of unrelated queries against "
            "the fitness corpus (no threshold applied). Evidence for the "
            "RAG_SIMILARITY_THRESHOLD decision:"
        )
        embeddings = provider.embed_texts(list(OFF_TOPIC_PROBE_QUERIES))
        for query_text, embedding in zip(OFF_TOPIC_PROBE_QUERIES, embeddings):
            chunks = retrieve_chunks(session, query_embedding=embedding, top_k=3)
            top = ", ".join(f"{c.similarity:.4f}" for c in chunks) or "(no chunks)"
            print(f"  {query_text}")
            print(f"    top-3 raw similarities: {top}")

    print("-" * 78)
    print(
        "Reminder: developer-written query set against a 6-document corpus.\n"
        "Not real-user evidence, not a population benchmark."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
