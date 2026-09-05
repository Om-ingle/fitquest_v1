"""Deterministic text chunking for the RAG knowledge base (Phase 4C.1).

Plain-text, character-based chunking — no NLP/tokenizer dependency, by
design (SRS keeps the stack lean). The contract:

- **Deterministic**: the same ``content`` + parameters always produce the
  exact same list of chunks (pure string operations, no randomness, no
  time dependence). This is what makes re-ingestion idempotent.
- **Order-preserving**: chunks follow document order; the i-th chunk covers
  text that comes before the (i+1)-th.
- **Stable indexes**: callers persist chunks with ``chunk_index`` 0..n-1;
  identical input re-produces identical indexes.
- **Paragraph-first**: text is split on blank lines and paragraphs are kept
  whole whenever they fit, so chunks start/end at natural boundaries.
- **Overlap**: each chunk after the first begins with the trailing
  ``overlap`` characters of the previous chunk (snapped forward to a word
  boundary so words are never cut at the overlap seam). 0 disables overlap.

Sizes are soft-bounded: a chunk is at most ``chunk_size`` characters of
*new* content, plus at most ``overlap`` carried-over characters.
"""

from __future__ import annotations

import re

from app.modules.rag.constants import CHUNK_OVERLAP, CHUNK_SIZE

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def _split_long_paragraph(paragraph: str, chunk_size: int) -> list[str]:
    """Split an oversized paragraph into word-packed segments, each
    <= chunk_size characters (a single word longer than chunk_size becomes
    its own, oversized, segment — words are never cut)."""
    words = paragraph.split(" ")
    segments: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= chunk_size:
            current = current + " " + word
        else:
            segments.append(current)
            current = word
    if current:
        segments.append(current)
    return segments


def _overlap_tail(previous_chunk: str, overlap: int) -> str:
    """The trailing ``overlap`` characters of a chunk, advanced past a cut
    word so the overlap never starts mid-word (deterministic)."""
    if overlap <= 0 or not previous_chunk:
        return ""
    tail = previous_chunk[-overlap:]
    space = tail.find(" ")
    if 0 < space < len(tail) - 1:
        tail = tail[space + 1 :]
    return tail


def chunk_text(
    content: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split ``content`` into deterministic, ordered, overlapping chunks.

    Raises ``ValueError`` for invalid parameters (chunk_size < 1, or
    overlap outside 0..chunk_size-1) and ``TypeError`` for non-string
    content. Empty or whitespace-only content yields ``[]`` — a document
    with nothing to chunk is rejected upstream, not silently kept.
    """
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            f"overlap must be in 0..chunk_size-1, got overlap={overlap}, "
            f"chunk_size={chunk_size}"
        )

    text = content.strip()
    if not text:
        return []

    # Paragraph pieces, each small enough to pack (oversized ones split).
    pieces: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_long_paragraph(paragraph, chunk_size))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 2 + len(piece) <= chunk_size:  # +2 for "\n\n"
            current = current + "\n\n" + piece
        else:
            chunks.append(current)
            tail = _overlap_tail(current, overlap)
            current = (tail + "\n\n" + piece) if tail else piece
    if current:
        chunks.append(current)

    return chunks
