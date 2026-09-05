"""Repeatable RAG corpus ingestion (Phase 4C.2).

    python -m app.modules.rag.ingestion [--database-url URL] [--dry-run]

Ingests the curated corpus (corpus.py) into the RAG knowledge base using
REAL Gemini embeddings — this script is the only supported way to seed
the knowledge base (no manual SQL inserts, no public HTTP endpoint).

Requires GEMINI_API_KEY in the environment / .env. Never run by the
automated test suite (tests use their own fixture providers and never
touch the network). The script never prints the API key or the database
URL.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine
from sqlmodel import Session

from app.core.config import settings
from app.modules.rag.corpus import CORPUS
from app.modules.rag.providers import get_embedding_provider
from app.modules.rag.service import ingest_document, list_documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL URL (default: DATABASE_URL from env/.env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate corpus + provider configuration without writing anything",
    )
    args = parser.parse_args(argv)

    # Fail loudly BEFORE opening a database connection if no provider is
    # configured — ingestion without real embeddings is not ingestion.
    provider = get_embedding_provider()
    print(f"Embedding provider ready (model {provider.model}, dim {provider.dimension})")

    for document in CORPUS:
        missing = [
            key for key in ("title", "source", "content", "metadata") if not document.get(key)
        ]
        if missing:
            print(f"ABORT: corpus document missing keys: {missing}", file=sys.stderr)
            return 1

    if args.dry_run:
        print(f"Dry run OK: {len(CORPUS)} corpus documents validated, nothing written.")
        return 0

    database_url = args.database_url or settings.database_url
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            for document in CORPUS:
                stored = ingest_document(
                    session,
                    title=document["title"],
                    source=document["source"],
                    content=document["content"],
                    provider=provider,
                    source_url=document.get("source_url"),
                    document_metadata=document["metadata"],
                )
                print(f"Ingested: [{stored.source}] {stored.title}")
        with Session(engine) as session:
            total = len(list_documents(session))
        print(f"Done. Knowledge base now lists {total} document(s).")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
