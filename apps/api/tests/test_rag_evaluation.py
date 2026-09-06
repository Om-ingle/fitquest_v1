"""Phase 4C.3A retrieval-evaluation tests: metric math, query-set
invariants, and the evaluation runner — all with FIXTURE providers and
FIXTURE documents (zero API calls, zero real-corpus dependency).

The live run against the real corpus is the manual tool
tools/evaluate_retrieval.py — never pytest.
"""
import uuid

import pytest
from sqlmodel import Session, SQLModel

from app.core.database import engine
from app.modules.rag import service as rag_service
from app.modules.rag.constants import EMBEDDING_DIMENSION
from app.modules.rag.evaluation import (
    EVALUATION_QUERIES,
    EvaluationQuery,
    recall_at_k,
    run_retrieval_evaluation,
    validate_queries,
)
from app.modules.rag.corpus import CORPUS


def basis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


FIXTURE_CONTENT = "TEST FIXTURE — placeholder text for evaluation tests."


class FixtureProvider:
    """TEST-ONLY: maps each query text to a chosen basis vector so which
    fixture documents a query retrieves is fully controlled by the test."""

    dimension = EMBEDDING_DIMENSION

    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping
        self.calls: list[list[str]] = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [self.mapping.get(text, basis(0)) for text in texts]


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed(db, title: str, vector: list[float]):
    rag_service.ingest_document(
        db, title=title, source="EVAL-FIXTURE", content=FIXTURE_CONTENT,
        provider=FixtureProvider({FIXTURE_CONTENT: vector}),
        chunk_size=60, overlap=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric math (pure)
# ─────────────────────────────────────────────────────────────────────────────


def test_recall_full_partial_and_zero():
    assert recall_at_k({"a", "b"}, {"a", "b", "c"}) == 1.0
    assert recall_at_k({"a", "b"}, {"a"}) == 0.5
    assert recall_at_k({"a"}, {"x", "y"}) == 0.0


def test_recall_ignores_duplicates_and_extras_in_retrieved():
    assert recall_at_k({"a", "b"}, ["a", "a", "b", "c", "c"]) == 1.0


def test_recall_requires_a_non_empty_expected_set():
    with pytest.raises(ValueError, match="non-empty expected"):
        recall_at_k(set(), {"a"})


# ─────────────────────────────────────────────────────────────────────────────
# Shipped query-set invariants
# ─────────────────────────────────────────────────────────────────────────────


def test_query_set_size_and_coverage():
    # 4C.3A scope: ~8-12 representative queries. Every query is a plain
    # user-style question (no medical-advice phrasing like "diagnose").
    assert 8 <= len(EVALUATION_QUERIES) <= 12
    for query in EVALUATION_QUERIES:
        assert len(query.query.strip()) > 20
        assert 1 <= len(query.expected_documents) <= 3


def test_query_set_is_validated_at_import():
    # The module validates its own shipped set at import time; corrupting a
    # copy must reproduce the same failure modes the import guard protects.
    with pytest.raises(ValueError, match="unknown documents"):
        validate_queries(
            [EvaluationQuery("bad", "some query text", frozenset({"No such document"}))]
        )
    with pytest.raises(ValueError, match="unique"):
        validate_queries(
            [
                EvaluationQuery("dup", "text one", frozenset({"a"})),
                EvaluationQuery("dup", "text two", frozenset({"a"})),
            ]
        )
    with pytest.raises(ValueError, match="no expected documents"):
        validate_queries([EvaluationQuery("empty-exp", "text", frozenset())])


def test_expected_documents_are_real_corpus_titles():
    corpus_titles = {document["title"] for document in CORPUS}
    for query in EVALUATION_QUERIES:
        assert query.expected_documents <= corpus_titles


def test_off_topic_probes_are_clearly_unrelated_to_fitness():
    from app.modules.rag.evaluation import OFF_TOPIC_PROBE_QUERIES

    assert 2 <= len(OFF_TOPIC_PROBE_QUERIES) <= 4
    # None of the probes may be about physical activity — otherwise the
    # "unrelated text" separation evidence would be invalid.
    for probe in OFF_TOPIC_PROBE_QUERIES:
        low = probe.lower()
        assert not any(
            word in low
            for word in ("walk", "exercise", "fitness", "activity", "steps", "health")
        )


# ─────────────────────────────────────────────────────────────────────────────
# Runner (fixture provider + fixture documents, SQLite)
# ─────────────────────────────────────────────────────────────────────────────


def _fixture_queries():
    return [
        EvaluationQuery("walking", "query about walking", frozenset({"doc-walking"})),
        EvaluationQuery(
            "recovery", "query about recovery", frozenset({"doc-recovery", "doc-rest"})
        ),
        EvaluationQuery("off", "query about nothing present", frozenset({"doc-absent"})),
    ]


def test_runner_computes_recall_and_hit_rate(db):
    _seed(db, "doc-walking", basis(1))
    _seed(db, "doc-recovery", basis(2))
    _seed(db, "doc-rest", basis(3))
    provider = FixtureProvider(
        {
            "query about walking": basis(1),       # exact match → recall 1.0
            "query about recovery": basis(2),      # 1 of 2 expected → 0.5
            "query about nothing present": basis(9),  # nothing → 0.0, miss
        }
    )

    report = run_retrieval_evaluation(
        db, provider=provider, top_k=2, min_similarity=0.5,
        queries=_fixture_queries(),
    )

    assert len(report.results) == 3
    by_label = {result.query.label: result for result in report.results}
    assert by_label["walking"].recall == 1.0 and by_label["walking"].hit
    assert by_label["recovery"].recall == 0.5 and by_label["recovery"].hit
    assert by_label["off"].recall == 0.0 and not by_label["off"].hit
    assert report.mean_recall_at_k == pytest.approx((1.0 + 0.5 + 0.0) / 3)
    assert report.hit_rate == pytest.approx(2 / 3)
    assert report.top_k == 2 and report.min_similarity == 0.5


def test_runner_threshold_filters_before_scoring(db):
    # Every chunk scores exactly 1.0 vs the walking query; a threshold of
    # 1.0 keeps them, a threshold above 1.0 is impossible for cosine and a
    # threshold that nothing meets must yield zero results (and thus
    # recall 0), not fabricated hits.
    _seed(db, "doc-walking", basis(1))
    provider = FixtureProvider({"query about walking": basis(1)})

    kept = run_retrieval_evaluation(
        db, provider=provider, top_k=2, min_similarity=0.5, queries=_fixture_queries()[:1]
    )
    assert kept.results[0].recall == 1.0

    filtered = run_retrieval_evaluation(
        db, provider=provider, top_k=2, min_similarity=0.999999,
        queries=_fixture_queries()[:1],
    )
    # basis(1) vs basis(1) is cosine 1.0 >= 0.999999 → still retrieved.
    assert filtered.results[0].chunks

    empty = run_retrieval_evaluation(
        # "off" query → basis(9), orthogonal to every seeded chunk, so even
        # the permissive 0.5 threshold filters everything → zero results.
        db, provider=provider, top_k=2, min_similarity=0.5,
        queries=_fixture_queries()[2:3],
    )
    assert empty.results[0].chunks == []
    assert empty.results[0].recall == 0.0


def test_runner_embeds_the_whole_query_set_in_one_batch(db):
    _seed(db, "doc-walking", basis(1))
    provider = FixtureProvider({"query about walking": basis(1)})

    run_retrieval_evaluation(db, provider=provider, top_k=1, queries=_fixture_queries())

    # One batched provider call containing every query text — the live tool
    # relies on this to spend one API call, not N.
    assert provider.calls == [[query.query for query in _fixture_queries()]]


def test_runner_rejects_a_provider_count_mismatch(db):
    class WrongCountProvider(FixtureProvider):
        def embed_texts(self, texts):
            return [basis(0) for _ in texts[:-1]]  # one short

    with pytest.raises(ValueError, match="embeddings for"):
        run_retrieval_evaluation(
            db, provider=WrongCountProvider({}), top_k=1, queries=_fixture_queries()
        )


def test_runner_validates_the_shipped_query_set_only_against_the_corpus(db):
    # Fixture queries reference fixture titles — the corpus-title check must
    # NOT fire for an explicitly passed query set (or every fixture test
    # above would fail). A regression here shows up as those tests failing.
    _seed(db, "doc-walking", basis(1))
    provider = FixtureProvider({"query about walking": basis(1)})
    report = run_retrieval_evaluation(
        db, provider=provider, top_k=1, queries=_fixture_queries()
    )
    assert report.results[0].hit
