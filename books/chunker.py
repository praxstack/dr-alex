"""Structure-aware chunking — heuristic chapter detection with an honest fallback.

Two detection strategies run per book, in order:

1. **Explicit heading lines** — ``CHAPTER 3`` / ``Chapter 3: Title`` / ``PART II`` /
   ``Module 2 …`` lines, with a cluster filter that removes tables of contents
   (heading candidates packed close together), first-occurrence dedupe (so a Notes
   section that repeats chapter numbers loses to the body), and a strictly-
   increasing-number filter.
2. **TOC fuzzy match** — parse a numbered table of contents near the top of the
   file, then locate each title's standalone occurrence in the body by fuzzy
   similarity (extractions drift, e.g. "Seff-Esteem" vs "Self-Esteem").

Every accepted heading set must pass sanity validation (count, span, gaps).
RIDER (binding): if neither strategy validates, the book falls back to
``{book, chunk_id}`` with ``chapter=None`` — chapter/section names are NEVER
invented.

Chunks target ~500-800 tokens (~4 chars/token) with a small overlap, and each
chunk carries a breadcrumb ("Feeling Good › Ch. 4 …") that is prepended to the
indexed text at index time (poor-man's contextual retrieval).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from books.manifest import BookSpec

TARGET_CHARS = 2800   # ~700 tokens
HARD_MAX_CHARS = 3400  # ~850 tokens
MIN_TAIL_CHARS = 700   # merge a smaller tail into the previous chunk
OVERLAP_CHARS = 300    # ~75 tokens carried between adjacent chunks


@dataclass(frozen=True)
class Heading:
    line_no: int
    pos: int
    label: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    book_slug: str
    book_title: str
    chapter: str | None
    breadcrumb: str
    text: str


# ---------------------------------------------------------------------------
# Strategy 1 — explicit heading lines
# ---------------------------------------------------------------------------

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_HEAD_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chapter", re.compile(r"^(?:CHAPTER|Chapter)\s+(?P<num>\d{1,2})(?P<sep>\s*[:.–—-]?)\s*(?P<rest>.*)$")),
    ("part", re.compile(
        r"^(?:PART|Part)\s+(?P<num>\d{1,2}|[IVXLCivxlc]{1,7}|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)"
        r"(?P<sep>\s*[:.–—-]?)\s*(?P<rest>.*)$")),
    ("module", re.compile(r"^(?:MODULE|Module)\s+(?P<num>\d{1,2})(?P<sep>\s*[:.–—-]?)\s*(?P<rest>.*)$")),
    ("session", re.compile(r"^(?:SESSION|Session)\s+(?P<num>\d{1,2})(?P<sep>\s*[:.–—-]?)\s*(?P<rest>.*)$")),
    ("step", re.compile(r"^(?:STEP|Step)\s+(?P<num>\d{1,2})(?P<sep>\s*[:.–—-]?)\s*(?P<rest>.*)$")),
    ("week", re.compile(r"^(?:WEEK|Week)\s+(?P<num>\d{1,2})(?P<sep>\s*[:.–—-]?)\s*(?P<rest>.*)$")),
)

_KIND_LABEL = {
    "chapter": "Ch.",
    "part": "Part",
    "module": "Module",
    "session": "Session",
    "step": "Step",
    "week": "Week",
}


def _num_value(raw: str) -> int | None:
    raw = raw.strip().lower()
    if raw.isdigit():
        return int(raw)
    if raw in _WORD_NUMS:
        return _WORD_NUMS[raw]
    if all(ch in _ROMAN for ch in raw):
        total, prev = 0, 0
        for ch in reversed(raw):
            val = _ROMAN[ch]
            total = total - val if val < prev else total + val
            prev = max(prev, val)
        return total or None
    return None


@dataclass(frozen=True)
class _Candidate:
    line_no: int
    kind: str
    num: int
    rest: str


def _title_like(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 70:
        return False
    if line[-1] in ",;":
        return False
    return not line.isdigit()


def _explicit_candidates(lines: list[str]) -> list[_Candidate]:
    out: list[_Candidate] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > 80:
            continue
        for kind, rx in _HEAD_RES:
            m = rx.match(line)
            if not m:
                continue
            num = _num_value(m.group("num"))
            if num is None:
                continue
            rest = m.group("rest").strip()
            if rest:
                first_alpha = next((c for c in rest if c.isalpha()), "")
                if first_alpha and first_alpha.islower():
                    continue  # prose: "Chapter 4 fosters the development…"
                if not any(c.isalnum() for c in rest):
                    continue  # cross-reference stub: "Chapter 9."
                if rest[-1] in ",;":
                    continue
            elif not m.group("sep").strip() and line[-1] in ".,;?!":
                continue
            out.append(_Candidate(line_no=i, kind=kind, num=num, rest=rest))
            break
    return out


def _drop_clusters(cands: list[_Candidate], window: int = 12, min_neighbors: int = 2) -> list[_Candidate]:
    kept: list[_Candidate] = []
    for c in cands:
        neighbors = sum(
            1 for o in cands if o is not c and abs(o.line_no - c.line_no) <= window
        )
        if neighbors < min_neighbors:
            kept.append(c)
    return kept


def _dedupe_keep_first(cands: list[_Candidate]) -> list[_Candidate]:
    seen: set[tuple[str, int]] = set()
    out: list[_Candidate] = []
    for c in cands:
        key = (c.kind, c.num)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _monotonic(cands: list[_Candidate]) -> list[_Candidate]:
    last: dict[str, int] = {}
    out: list[_Candidate] = []
    for c in cands:
        if c.num <= last.get(c.kind, 0):
            continue
        last[c.kind] = c.num
        out.append(c)
    return out


# Private-use-area and dingbat/wingding glyphs that PDF extraction sometimes leaves
# where a bullet or ornament used to be. They are never part of a real chapter title,
# so strip them — a breadcrumb must carry only text that is actually in the book.
_GLYPH_RE = re.compile(
    "[\ue000-\uf8ff\U000f0000-\U000ffffd\u2400-\u27bf\ufffc\ufffd]"
)


def _clean_title(title: str) -> str:
    title = _GLYPH_RE.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip(" .,:;–—- ")
    return title


def _enrich_label(c: _Candidate, lines: list[str]) -> str:
    prefix = f"{_KIND_LABEL[c.kind]} {c.num}"
    title = _clean_title(c.rest)
    if not title:
        for j in range(c.line_no + 1, min(c.line_no + 5, len(lines))):
            nxt = lines[j].strip()
            if not nxt:
                continue
            if _title_like(nxt) and not any(rx.match(nxt) for _, rx in _HEAD_RES):
                title = _clean_title(nxt)
            break
    return f"{prefix} {title}".strip() if title else prefix


def _plausible_numbering(cands: list[_Candidate]) -> bool:
    """Reject heading sets whose numbering is too sparse or starts too high.

    A real chapter/module/session run starts near the beginning (min <= 3) and is
    reasonably contiguous (>= half the numbers between min and max are present). A set
    like {9, 25, 30} — three lone hits scattered through a 600-page book — is a
    detection failure that would MIS-attribute most content to the wrong chapter, so
    we fall back to ``{book, chunk_id}`` rather than invent structure. (RIDER: never
    invent or mis-attribute chapter names.)
    """
    primary = max(_KIND_LABEL, key=lambda k: sum(1 for c in cands if c.kind == k))
    nums = sorted(c.num for c in cands if c.kind == primary)
    if len(nums) < 3:
        return False
    if nums[0] > 3:
        return False
    coverage = len(nums) / (nums[-1] - nums[0] + 1)
    return coverage >= 0.5


def _explicit_headings(lines: list[str], offsets: list[int]) -> list[Heading]:
    cands = _explicit_candidates(lines)
    cands = _drop_clusters(cands)
    cands = _dedupe_keep_first(cands)
    cands = _monotonic(cands)
    # Chapters (or modules/sessions/…) carry the structure; parts alone are too
    # coarse. Require at least 3 non-part headings.
    non_part = [c for c in cands if c.kind != "part"]
    if len(non_part) < 3:
        return []
    if not _plausible_numbering(cands):
        return []
    return [
        Heading(line_no=c.line_no, pos=offsets[c.line_no], label=_enrich_label(c, lines))
        for c in cands
    ]


# ---------------------------------------------------------------------------
# Strategy 2 — TOC fuzzy match
# ---------------------------------------------------------------------------

_TOC_ENTRY_RE = re.compile(r"^\s*(?:Chapter\s+)?(?P<num>\d{1,2})[.:]\s+(?P<title>\S.{3,68})$")
_TOC_SCAN_LINES = 400
_TOC_MIN_ENTRIES = 5
_TOC_MATCH_RATIO = 0.78
_TOC_MIN_FOUND = 0.6


def _norm_title(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _toc_entries(lines: list[str]) -> list[tuple[int, int, str]]:
    entries: list[tuple[int, int, str]] = []
    last_num = 0
    for i, raw in enumerate(lines[:_TOC_SCAN_LINES]):
        m = _TOC_ENTRY_RE.match(raw.strip())
        if not m:
            continue
        num = int(m.group("num"))
        if num != last_num + 1:
            continue
        entries.append((i, num, m.group("title").strip()))
        last_num = num
    return entries


def _toc_headings(lines: list[str], offsets: list[int]) -> list[Heading]:
    entries = _toc_entries(lines)
    if len(entries) < _TOC_MIN_ENTRIES:
        return []
    toc_end = entries[-1][0]
    norm_lines = [_norm_title(ln) if 0 < len(ln.strip()) <= 80 else "" for ln in lines]

    found: list[Heading] = []
    search_from = toc_end + 1
    for _, num, title in entries:
        norm_t = _norm_title(title)
        if len(norm_t) < 4:
            continue
        first_word = norm_t.split(" ", 1)[0]
        best: tuple[int, str] | None = None
        for j in range(search_from, len(lines)):
            cand = norm_lines[j]
            if not cand or not cand.startswith(first_word):
                continue
            joined = cand
            if len(cand) < len(norm_t) - 8 and j + 1 < len(lines) and norm_lines[j + 1]:
                joined = f"{cand} {norm_lines[j + 1]}"
            for attempt in (cand, joined):
                if abs(len(attempt) - len(norm_t)) > max(10, len(norm_t) // 2):
                    continue
                if difflib.SequenceMatcher(None, attempt, norm_t).ratio() >= _TOC_MATCH_RATIO:
                    best = (j, lines[j].strip())
                    break
            if best:
                break
        if best:
            j, body_title = best
            found.append(Heading(line_no=j, pos=offsets[j], label=f"Ch. {num} {body_title}"))
            search_from = j + 1
    if len(found) < max(3, int(len(entries) * _TOC_MIN_FOUND)):
        return []
    return found


# ---------------------------------------------------------------------------
# Validation + public detection API
# ---------------------------------------------------------------------------


def _validated(headings: list[Heading], text_len: int) -> list[Heading]:
    if len(headings) < 3 or len(headings) > 100:
        return []
    if headings[0].pos > text_len * 0.5:
        return []
    if (headings[-1].pos - headings[0].pos) < text_len * 0.3:
        return []
    gaps = [b.pos - a.pos for a, b in zip(headings, headings[1:], strict=False)]
    gaps.sort()
    if gaps and gaps[len(gaps) // 2] < 1500:
        return []
    return headings


def detect_headings(text: str) -> list[Heading]:
    """Detected section headings, or [] when structure detection fails (fallback)."""
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1
    for strategy in (_explicit_headings, _toc_headings):
        headings = _validated(strategy(lines, offsets), len(text))
        if headings:
            return headings
    return []


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _split_section(section: str) -> list[str]:
    """Split one section into ~TARGET_CHARS pieces on line boundaries, with overlap."""
    lines = section.split("\n")
    pieces: list[str] = []
    buf: list[str] = []
    size = 0
    for ln in lines:
        buf.append(ln)
        size += len(ln) + 1
        if size >= TARGET_CHARS and (not ln.strip() or size >= HARD_MAX_CHARS):
            piece = "\n".join(buf).strip()
            if piece:
                pieces.append(piece)
            overlap: list[str] = []
            osize = 0
            for prev in reversed(buf):
                osize += len(prev) + 1
                overlap.insert(0, prev)
                if osize >= OVERLAP_CHARS:
                    break
            buf = list(overlap)
            size = sum(len(x) + 1 for x in buf)
    tail = "\n".join(buf).strip()
    if tail:
        # The tail always begins with the overlap already present in the previous
        # piece; only keep it when it adds enough new material.
        new_material = len(tail) if not pieces else len(tail) - OVERLAP_CHARS
        if pieces and new_material < MIN_TAIL_CHARS:
            pass
        else:
            pieces.append(tail)
    return pieces


def chunk_book(spec: BookSpec, text: str) -> list[Chunk]:
    """Chunk one book's full text into breadcrumbed, citable chunks."""
    headings = detect_headings(text)
    sections: list[tuple[str | None, str]] = []
    if not headings:
        sections.append((None, text))
    else:
        if headings[0].pos > 0:
            sections.append((None, text[: headings[0].pos]))
        for h, nxt in zip(headings, [*headings[1:], None], strict=False):
            end = nxt.pos if nxt is not None else len(text)
            sections.append((h.label, text[h.pos:end]))

    chunks: list[Chunk] = []
    n = 0
    for chapter, body in sections:
        if len(body.strip()) < 200:
            continue
        breadcrumb = (
            f"{spec.short_title} › {chapter}" if chapter else spec.short_title
        )
        for piece in _split_section(body):
            chunks.append(
                Chunk(
                    chunk_id=f"{spec.slug}:{n:04d}",
                    book_slug=spec.slug,
                    book_title=spec.title,
                    chapter=chapter,
                    breadcrumb=breadcrumb,
                    text=piece,
                )
            )
            n += 1
    return chunks


def indexed_text(chunk: Chunk) -> str:
    """Breadcrumb-prefixed text, the string the FTS index actually stores."""
    return f"{chunk.breadcrumb}\n{chunk.text}"
