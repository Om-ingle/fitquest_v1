"""Phase 4C.1 RAG constants.

The single, explicit home for values that must not be scattered:

- ``EMBEDDING_DIMENSION`` — the vector width of the ``ragchunk.embedding``
  column (Alembic migration 0003 freezes the same value into the database
  schema; changing it later requires re-embedding every chunk AND a new
  migration, so it is a deliberate decision point, not a tuneable). No
  embedding provider exists in the repository yet — 1536 is the common
  default width (e.g. OpenAI ``text-embedding-3-small``) chosen so the
  schema is usable while Phase 4C.2 selects the actual provider. If 4C.2
  picks a different model width, add a migration that alters the column
  and re-embed; do NOT edit this constant and hope.
- ``CHUNK_SIZE`` / ``CHUNK_OVERLAP`` — default chunking parameters
  (characters). Overridable per call; see chunking.py.
"""

EMBEDDING_DIMENSION = 1536

# Default chunking parameters (characters of text, not tokens — no NLP
# dependency by design). See app/modules/rag/chunking.py for the algorithm.
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
