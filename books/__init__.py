"""Book grounding for Dr. Alex Morgan — corpus manifest, ingestion, and retrieval.

Phase 2: the 13-book clinical library is chunked structure-aware, indexed into a
local SQLite FTS5/BM25 database (derived, gitignored, fully rebuildable), and
queried per turn AFTER safety triage. Book text is evidence, not personalized
instruction; every retrieved chunk carries {book, chapter, chunk_id} so the model
can cite [B#] labels that deterministic gates can verify.
"""

from books.manifest import BookSpec, all_books, excluded_books, included_books
from books.retriever import BookRetriever, Embedder, RetrievedChunk

__all__ = [
    "BookSpec",
    "all_books",
    "included_books",
    "excluded_books",
    "BookRetriever",
    "Embedder",
    "RetrievedChunk",
]
