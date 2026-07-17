"""Structure-aware chunking + the honest {book, chunk_id} fallback (binding rider)."""

from __future__ import annotations

from books.chunker import (
    TARGET_CHARS,
    _clean_title,
    _plausible_numbering,
    _Candidate,
    chunk_book,
    detect_headings,
    indexed_text,
)
from books.manifest import BookSpec

_SPEC = BookSpec(
    slug="demo", title="Demo Book: A Full Title", short_title="Demo Book",
    authors="A. Author", filename="demo.txt",
)


def _para(word: str, n: int = 400) -> str:
    return (" ".join([word] * 12) + "\n") * n


def _multi_chapter_text() -> str:
    parts = []
    for i in range(1, 6):
        parts.append(f"Chapter {i}: The {['First','Second','Third','Fourth','Fifth'][i-1]} Idea")
        parts.append("")
        parts.append(_para(f"content{i}"))
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Title cleaning — never carry PDF glyph noise into a breadcrumb.
# ---------------------------------------------------------------------------


def test_clean_title_strips_private_use_glyphs() -> None:
    assert _clean_title("") == ""            # wingding pointer
    assert _clean_title("Adaptive Thinking ") == "Adaptive Thinking"


def test_clean_title_preserves_real_hyphens() -> None:
    assert _clean_title("Self-Esteem and You") == "Self-Esteem and You"


# ---------------------------------------------------------------------------
# Numbering plausibility — reject scattered detections that would mis-attribute.
# ---------------------------------------------------------------------------


def _cands(kind: str, nums: list[int]) -> list[_Candidate]:
    return [_Candidate(line_no=i, kind=kind, num=n, rest="") for i, n in enumerate(nums)]


def test_plausible_numbering_accepts_contiguous_from_one() -> None:
    assert _plausible_numbering(_cands("chapter", [1, 2, 3, 4, 5])) is True


def test_plausible_numbering_rejects_scattered_high_start() -> None:
    # The taking-charge failure mode: three lone hits at 9/25/30.
    assert _plausible_numbering(_cands("chapter", [9, 25, 30])) is False


def test_plausible_numbering_rejects_sparse() -> None:
    assert _plausible_numbering(_cands("chapter", [1, 2, 30])) is False


# ---------------------------------------------------------------------------
# Detection + chunking
# ---------------------------------------------------------------------------


def test_detects_chapters_and_breadcrumbs() -> None:
    text = _multi_chapter_text()
    heads = detect_headings(text)
    assert len(heads) >= 3
    chunks = chunk_book(_SPEC, text)
    assert chunks
    chaptered = [c for c in chunks if c.chapter]
    assert chaptered, "expected some chaptered chunks"
    c = chaptered[0]
    # Breadcrumb = short title › chapter, and it is prepended to the indexed text.
    assert c.breadcrumb.startswith("Demo Book")
    assert "Ch." in c.breadcrumb
    assert indexed_text(c).startswith(c.breadcrumb)


def test_fallback_when_no_structure_never_invents_chapters() -> None:
    # A wall of prose with no headings must fall back to {book, chunk_id}.
    text = _para("plainprose", 600)
    assert detect_headings(text) == []
    chunks = chunk_book(_SPEC, text)
    assert chunks
    assert all(c.chapter is None for c in chunks)
    # Breadcrumb is just the book — no fabricated section name.
    assert all(c.breadcrumb == _SPEC.short_title for c in chunks)


def test_chunk_ids_unique_and_slug_prefixed() -> None:
    chunks = chunk_book(_SPEC, _multi_chapter_text())
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(cid.startswith("demo:") for cid in ids)


def test_chunks_are_bounded_in_size() -> None:
    chunks = chunk_book(_SPEC, _multi_chapter_text())
    # Allow a generous ceiling (hard max + overlap), but nothing pathological.
    assert all(len(c.text) <= TARGET_CHARS * 2 for c in chunks)
