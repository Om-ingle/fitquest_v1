"""Project-level retrieval-quality evaluation (Phase 4C.3A).

A SMALL, fixed, deterministic evaluation suite for the curated knowledge
corpus: ~10 representative coaching queries, each labeled with the corpus
documents a domain expert would expect retrieval to surface, plus simple
metrics (Recall@k, hit rate).

⚠ Honesty note (SRS §26 — never claim more than was measured): this is a
PROJECT-LEVEL SANITY EVALUATION, not a scientific benchmark. The query set
was written by the project's developers against the project's own 6-document
corpus; the "expected" labels are developer judgment, not a labeled
population sample. The numbers say "retrieval finds the documents we think
it should for the queries we expect FitQuest users to ask" — nothing more.

What is deterministic: the query set, the expectations, the metric math,
and (for a fixed embedding model) the query embeddings themselves. What is
NOT guaranteed: absolute similarity scores can drift if the embedding model
is retrained upstream, so recorded numbers are a snapshot, not a contract.

No test in the automated suite runs this against a real provider —
``run_retrieval_evaluation`` takes an injected provider, tests pass fakes,
and the live run is the manual tool ``tools/evaluate_retrieval.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AbstractSet, Iterable, Optional, Sequence

from sqlmodel import Session

from app.modules.rag.corpus import CORPUS
from app.modules.rag.providers import EmbeddingProvider
from app.modules.rag.schemas import RetrievedChunk
from app.modules.rag.service import retrieve_chunks

# Every title referenced by the query set must exist in the curated corpus —
# an expectation pointing at a document that doesn't exist is a bug in the
# evaluation, not a retrieval failure.
CORPUS_TITLES: frozenset[str] = frozenset(doc["title"] for doc in CORPUS)


@dataclass(frozen=True)
class EvaluationQuery:
    """One labeled evaluation query.

    ``expected_documents`` is the set of corpus TITLES a reviewer would
    consider relevant for this query — the denominator of Recall@k.
    Kept small (1-3 titles) on purpose: with 6 corpus documents, huge
    expectation sets would make the metric meaningless.
    """

    label: str
    query: str
    expected_documents: frozenset[str]


EVALUATION_QUERIES: list[EvaluationQuery] = [
    EvaluationQuery(
        label="cold-start-beginner",
        query=(
            "I'm brand new to exercise and have never been active regularly. "
            "What is a safe way to start being more active every day?"
        ),
        expected_documents=frozenset(
            {
                "Physical activity guidelines for adults",
                "Walking as everyday physical activity",
            }
        ),
    ),
    EvaluationQuery(
        label="walking-consistency",
        query="How do I build a consistent daily walking habit?",
        expected_documents=frozenset(
            {
                "Walking as everyday physical activity",
                "Building activity consistency and habits",
            }
        ),
    ),
    EvaluationQuery(
        label="gradual-progression",
        query=(
            "My daily walks feel easy now. When and how should I increase "
            "the distance or pace?"
        ),
        expected_documents=frozenset({"Gradual progression and the principle of overload"}),
    ),
    EvaluationQuery(
        label="recovery-rest-days",
        query="Do I need rest days, or is it fine to be active every day?",
        expected_documents=frozenset({"Recovery and rest days"}),
    ),
    EvaluationQuery(
        label="weekly-activity-guidelines",
        query="How much physical activity should an adult get each week?",
        expected_documents=frozenset({"Physical activity guidelines for adults"}),
    ),
    EvaluationQuery(
        label="inactive-lapsed-return",
        query=(
            "I haven't exercised in about a month. How do I get back into "
            "activity safely?"
        ),
        expected_documents=frozenset(
            {
                "Returning to activity after a break",
                "Gradual progression and the principle of overload",
            }
        ),
    ),
    EvaluationQuery(
        label="motivation-consistency",
        query=(
            "I keep losing motivation and skipping days. How do I stay "
            "consistent with being active?"
        ),
        expected_documents=frozenset(
            {
                "Building activity consistency and habits",
                "Returning to activity after a break",
            }
        ),
    ),
    EvaluationQuery(
        label="general-safe-activity",
        query="Is walking every day safe for most adults?",
        expected_documents=frozenset(
            {
                "Walking as everyday physical activity",
                "Physical activity guidelines for adults",
            }
        ),
    ),
    EvaluationQuery(
        label="soreness-after-return",
        query=(
            "My legs are sore after my first walk in weeks. Should I keep "
            "going or take it easier?"
        ),
        expected_documents=frozenset(
            {
                "Recovery and rest days",
                "Returning to activity after a break",
            }
        ),
    ),
    EvaluationQuery(
        label="everyday-activity-counting",
        query=(
            "What counts as physical activity — do everyday things like "
            "taking the stairs or short walks count?"
        ),
        expected_documents=frozenset(
            {
                "Walking as everyday physical activity",
                "Physical activity guidelines for adults",
            }
        ),
    ),
]

# Clearly unrelated queries used ONLY to probe raw similarity scores against
# the fitness corpus (for similarity-threshold decisions). They are NOT part
# of the Recall@k evaluation — there is nothing relevant for them to recall.
OFF_TOPIC_PROBE_QUERIES: tuple[str, ...] = (
    "How do I bake sourdough bread with a wild yeast starter?",
    "Explain the basics of quantum computing and qubits.",
    "What should I look for when buying a used car?",
)


@dataclass
class QueryResult:
    """Retrieval outcome + metrics for one evaluation query."""

    query: EvaluationQuery
    chunks: list[RetrievedChunk] = field(default_factory=list)
    recall: float = 0.0
    hit: bool = False


@dataclass
class EvaluationReport:
    """Aggregate result of one evaluation run."""

    top_k: int
    min_similarity: Optional[float]
    results: list[QueryResult] = field(default_factory=list)
    mean_recall_at_k: float = 0.0
    hit_rate: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Metrics (pure)
# ─────────────────────────────────────────────────────────────────────────────


def recall_at_k(expected: AbstractSet[str], retrieved: Iterable[str]) -> float:
    """Fraction of the expected documents that appear among the retrieved
    documents. ``expected`` must be non-empty (an expectation-free query
    cannot be scored — that is an evaluation bug, not a 100%)."""
    if not expected:
        raise ValueError("recall_at_k requires a non-empty expected set")
    retrieved_set = set(retrieved)
    return len(expected & retrieved_set) / len(expected)


def validate_queries(
    queries: Sequence[EvaluationQuery], *, require_corpus_titles: bool = True
) -> None:
    """Structural invariants of any evaluation query set.

    ``require_corpus_titles`` additionally checks that every expected
    document is a real curated-corpus title — true for the shipped
    ``EVALUATION_QUERIES``, false for test fixture sets that reference
    fixture documents.
    """
    if not queries:
        raise ValueError("evaluation query set must not be empty")
    labels = [query.label for query in queries]
    if len(set(labels)) != len(labels):
        raise ValueError("evaluation query labels must be unique")
    for query in queries:
        if not query.query.strip():
            raise ValueError(f"evaluation query {query.label!r} has empty text")
        if not query.expected_documents:
            raise ValueError(f"evaluation query {query.label!r} has no expected documents")
        if require_corpus_titles:
            unknown = query.expected_documents - CORPUS_TITLES
            if unknown:
                raise ValueError(
                    f"evaluation query {query.label!r} expects unknown documents: "
                    f"{sorted(unknown)}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Runner (provider injected — tests use fakes, the manual tool uses Gemini)
# ─────────────────────────────────────────────────────────────────────────────


def run_retrieval_evaluation(
    db: Session,
    *,
    provider: EmbeddingProvider,
    top_k: int = 4,
    min_similarity: Optional[float] = None,
    queries: Optional[Sequence[EvaluationQuery]] = None,
) -> EvaluationReport:
    """Run the query set against the knowledge base in ``db``.

    Embeds ALL query texts in ONE provider batch (one API call for the real
    provider), retrieves ``top_k`` chunks per query with ``min_similarity``
    applied, and computes Recall@k per query plus mean Recall@k and hit rate
    over the set. ``queries`` defaults to ``EVALUATION_QUERIES``; tests pass
    their own fixture queries with an injected fixture provider.
    """
    query_set = list(queries) if queries is not None else list(EVALUATION_QUERIES)
    # Fixture query sets legitimately reference fixture documents, so the
    # corpus-title check only applies to the shipped query set.
    validate_queries(query_set, require_corpus_titles=queries is None)

    embeddings = provider.embed_texts([query.query for query in query_set])
    if len(embeddings) != len(query_set):
        raise ValueError(
            f"provider returned {len(embeddings)} embeddings for "
            f"{len(query_set)} queries"
        )

    results: list[QueryResult] = []
    for query, embedding in zip(query_set, embeddings):
        chunks = retrieve_chunks(
            db, query_embedding=embedding, top_k=top_k, min_similarity=min_similarity
        )
        retrieved_titles = {chunk.document_title for chunk in chunks}
        results.append(
            QueryResult(
                query=query,
                chunks=chunks,
                recall=recall_at_k(query.expected_documents, retrieved_titles),
                hit=bool(query.expected_documents & retrieved_titles),
            )
        )

    count = len(results)
    return EvaluationReport(
        top_k=top_k,
        min_similarity=min_similarity,
        results=results,
        mean_recall_at_k=sum(result.recall for result in results) / count,
        hit_rate=sum(1 for result in results if result.hit) / count,
    )


# The shipped query set must satisfy its own invariants at import time —
# a broken expectation set is a bug in the evaluation, not a test finding.
validate_queries(EVALUATION_QUERIES)
