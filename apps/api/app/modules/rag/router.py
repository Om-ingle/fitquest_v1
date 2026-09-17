"""RAG API surface (Phase 4C.1; ingestion added in M11 / F-18).

- ``POST /rag/retrieve``: vector similarity search. The caller supplies the
  query embedding (the coach flow produces one server-side instead).
- ``GET /rag/documents``: read-only listing of ingested documents.
- ``POST /rag/documents``: **administrator-only** ingestion. This is the F-18
  requirement — an authenticated ingestion API — and it is the first time
  ``service.ingest_document`` is reachable over HTTP.

Why the earlier "no ingestion endpoint on purpose" note is now wrong: it said
ingestion should stay off the wire *because auth was deferred and every caller
was the dev user*. M11 makes a caller provable, so the endpoint can exist and be
gated. The gate is the ``ADMIN_USER_IDS`` subject allow-list, which is empty by
default — so this route is closed until an operator opts in, and every other
authenticated account gets a 403 rather than a write into the vector store.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.dependencies import get_db, require_admin
from app.modules.rag.providers import (
    EmbeddingProviderError,
    EmbeddingProviderNotConfigured,
    EmbeddingProviderTimeout,
    get_embedding_provider,
)
from app.modules.rag.schemas import (
    DocumentInfo,
    IngestionRequest,
    RetrievalRequest,
    RetrievalResponse,
)
from app.modules.rag.service import (
    get_document_info,
    ingest_document,
    list_documents,
    retrieve_chunks,
)

router = APIRouter()


@router.post("/retrieve", response_model=RetrievalResponse)
def retrieve_endpoint(
    request: RetrievalRequest, db: Session = Depends(get_db)
) -> RetrievalResponse:
    """Similarity search over the knowledge base (most similar first)."""
    results = retrieve_chunks(
        db,
        query_embedding=request.query_embedding,
        top_k=request.top_k,
        source=request.source,
        metadata_filters=request.metadata,
        min_similarity=request.min_similarity,
    )
    return RetrievalResponse(results=results)


@router.get("/documents", response_model=list[DocumentInfo])
def documents_endpoint(db: Session = Depends(get_db)) -> list[DocumentInfo]:
    """Read-only listing of knowledge-base documents with chunk counts."""
    return list_documents(db)


@router.post(
    "/documents",
    response_model=DocumentInfo,
    status_code=status.HTTP_201_CREATED,
)
def ingest_document_endpoint(
    payload: IngestionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> DocumentInfo:
    """Ingest (chunk + embed + upsert) one knowledge-base document.

    Idempotent on ``(source, title)``: re-ingesting replaces the document's
    content, metadata and chunks rather than duplicating it — the same
    guarantee ``ingestion.py`` relies on for its repeatable corpus load.

    Error mapping mirrors the coach endpoint: upstream failures are never a
    silent 200.
    - no embedding provider configured   → 503
    - embedding timeout                  → 504
    - provider transport/API error       → 502
    - content/title/source the service refuses → 422
    """
    try:
        provider = get_embedding_provider()
    except EmbeddingProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        document = ingest_document(
            db,
            title=payload.title,
            source=payload.source,
            content=payload.content,
            provider=provider,
            source_url=payload.source_url,
            document_metadata=payload.metadata,
        )
    except EmbeddingProviderTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except EmbeddingProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    info = get_document_info(db, document.id)
    if info is None:  # pragma: no cover — the document was just committed
        raise HTTPException(
            status_code=500, detail="Ingested document could not be read back"
        )
    return info
