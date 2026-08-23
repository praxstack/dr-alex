#!/usr/bin/env python3
"""Reconstruct dr-alex's missing book corpus txts from data/index/books.db.
The migration lost agent-memory-staging/claude-export/dr-alex-books; the built
FTS index still carries every chunk body. One txt per included book, chunks
joined in chunk_id order."""
import sqlite3, sys, pathlib
sys.path.insert(0, "/Users/prax/dr-alex")
from books import manifest  # noqa: E402

DB = pathlib.Path("/Users/prax/dr-alex/data/index/books.db")
corpus = manifest.corpus_dir()
corpus.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()
restored = []
for spec in manifest.included_books():
    rows = cur.execute(
        "SELECT chunk_id, body FROM chunks WHERE book_slug=? ORDER BY chunk_id", (spec.slug,)
    ).fetchall()
    if not rows:
        print(f"MISSING FROM INDEX: {spec.slug}"); continue
    text = "\n\n".join(body.strip() for _, body in rows)
    out = corpus / spec.filename
    out.write_text(text + "\n", encoding="utf-8")
    restored.append((spec.slug, len(rows), len(text)))
con.close()
for slug, n, size in restored:
    print(f"  {slug}: {n} chunks -> {size:,} bytes")
print(f"RESTORED {len(restored)}/13 books into {corpus}")
