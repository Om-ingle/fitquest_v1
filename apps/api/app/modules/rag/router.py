"""RAG API surface (Phase 4C.1) — deliberately minimal.

- ``POST /rag/retrieve``: vector similarity search. The caller supplies the
  query embedding (no embedding provider exists yet — 4C.2 wires one in;
  this endpoint is the honest way to exercise the retrieval pipeline).
- ``GET /rag/documents``: read-only listing of ingested documents.

There is NO ingestion endpoint on purpose: FitQuest auth is deferred (see
app/api/dependencies.py) and administrative document ingestion should not
be publicly reachable while every caller is the dev user. Ingestion is a
service-level operation (``app.modules.rag.service.ingest_document``) used
by the future ingestion path / seed tooling.
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.dependencies import get_db
from app.modules.rag.schemas import (
    DocumentInfo,
    RetrievalRequest,
    RetrievalResponse,
)
from app.modules.rag.service import list_documents, retrieve_chunks

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
