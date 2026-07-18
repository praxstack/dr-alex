"""The canonical local record — ``records/Active-File.md`` (council D4).

This is the human-readable source of truth for Dr. Alex: an identity header, the living
pattern docs, a session log, homework, a medication-timeline placeholder, and open threads.
It is written LOCALLY FIRST — before any Notion mirror — so local truth never depends on a
network round-trip (council D4). The Notion mirror and the exporters all READ the configured
path; none of them hardcode it (D4 rider 3).

Storage discipline (council D4 riders 1–2):
  * ``records/`` is created 0700, the file 0600, and ``records/`` is gitignored (the
    Directive-3 hygiene guard asserts it never enters git).
  * The file stays **plaintext markdown**. A human-readable canonical record is the whole
    point; encrypting it would just add decrypt-tool friction for the one person allowed to
    read it. The compensating control is the Phase-4 FileVault-off startup warning + the file
    perms + the gitignore.

Update model: human-owned sections (Identity, Living Pattern Docs, Medication timeline) are
preserved verbatim across updates; machine-owned sections (Session Log, Homework, Open
Threads) are rebuilt. A session-log entry is keyed by the ULID ``session_id`` so re-running a
session-end (idempotent replay) updates the entry in place rather than duplicating it.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dr_alex import config, timeutil
from dr_alex.digest import SessionDigest

# Top-level section headers, in canonical order.
_H_IDENTITY = "## Identity"
_H_PATTERNS = "## Living Pattern Docs"
_H_SESSIONS = "## Session Log"
_H_HOMEWORK = "## Homework"
_H_MEDS = "## Medication Timeline"
_H_THREADS = "## Open Threads"

_ENTRY_BOUNDARY = "### session "

_FILE_HEADER = (
    "<!-- Dr. Alex Morgan — canonical Active File (council D4). LOCAL TRUTH: written here\n"
    "     BEFORE any Notion mirror. Plaintext markdown is deliberate (human-readable canonical\n"
    "     record). records/ is 0700, this file 0600, gitignored. PraxVault migration: set\n"
    "     [records].active_file in config.toml — every reader resolves the configured path. -->\n"
)

_DEFAULT_IDENTITY = (
    "- Client: Prax\n"
    "- Working with: Shreya (therapist)\n"
    "- Dr. Alex is: support between sessions, not a replacement for Shreya or a clinician\n"
)

_DEFAULT_PATTERNS_BODY = (
    "<!-- Named, durable patterns. Each `### Name` below is a living pattern doc; the Friday\n"
    "     Shreya-prep packet reports which of these did and did NOT surface each window. Add a\n"
    "     pattern by writing a `### Name` heading; an optional `aliases: a, b, c` line lets the\n"
    "     packet's matcher catch phrasings that differ from the heading. This section is\n"
    "     human-owned and preserved verbatim across app updates. -->\n"
    "\n"
    "_No named patterns yet — Prax and Shreya name them here as they emerge._\n"
)

_DEFAULT_MEDS_BODY = (
    "<!-- Placeholder. Medication is Prax's + Shreya's domain; Dr. Alex only ever surfaces\n"
    "     self-reports, never a dose or a change. Human-owned; preserved verbatim. -->\n"
    "\n"
    "_No medication entries recorded._\n"
)


# ---------------------------------------------------------------------------
# Location + perms
# ---------------------------------------------------------------------------


def active_file_path(path: Path | None = None) -> Path:
    return Path(path) if path is not None else config.active_file_path()


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass


def _write(p: Path, text: str) -> None:
    _ensure_dir(p)
    existed = p.exists()
    p.write_text(text, encoding="utf-8")
    if not existed:
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    else:
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


def read_text(path: Path | None = None) -> str | None:
    p = active_file_path(path)
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Section parsing (top-level ``## `` headers)
# ---------------------------------------------------------------------------


def _split_sections(text: str) -> dict[str, str]:
    """Map each top-level ``## Header`` to its body text (everything up to the next ``## ``)."""
    sections: dict[str, str] = {}
    if not text:
        return sections
    # Split on lines that start a top-level header.
    parts = re.split(r"(?m)^(##\s+.+)$", text)
    # parts = [preamble, header1, body1, header2, body2, ...]
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections[header] = body.strip("\n")
    return sections


def _section(sections: dict[str, str], header: str, default: str) -> str:
    body = sections.get(header)
    return body if body and body.strip() else default


# ---------------------------------------------------------------------------
# Living pattern docs
# ---------------------------------------------------------------------------


@dataclass
class PatternDoc:
    name: str
    aliases: list[str]


def parse_pattern_docs(text: str | None) -> list[PatternDoc]:
    """Extract named living pattern docs (``### Name`` + optional ``aliases:`` line)."""
    if not text:
        return []
    sections = _split_sections(text)
    body = sections.get(_H_PATTERNS, "")
    if not body:
        return []
    docs: list[PatternDoc] = []
    # Each pattern is a ``### Name`` subsection.
    chunks = re.split(r"(?m)^###\s+(.+)$", body)
    for i in range(1, len(chunks), 2):
        name = chunks[i].strip()
        sub = chunks[i + 1] if i + 1 < len(chunks) else ""
        aliases: list[str] = []
        m = re.search(r"(?mi)^\s*aliases:\s*(.+)$", sub)
        if m:
            aliases = [a.strip() for a in re.split(r"[,;]", m.group(1)) if a.strip()]
        if name:
            docs.append(PatternDoc(name=name, aliases=aliases))
    return docs


def living_pattern_names(path: Path | None = None) -> list[str]:
    return [d.name for d in parse_pattern_docs(read_text(path))]


# ---------------------------------------------------------------------------
# Session-log entries (keyed by session_id for idempotent replay)
# ---------------------------------------------------------------------------


def _parse_session_entries(sessions_body: str) -> list[tuple[str, str]]:
    """Return [(session_id, entry_markdown)] preserving order; robust to hand edits."""
    entries: list[tuple[str, str]] = []
    if not sessions_body:
        return entries
    # Split keeping the boundary token off; each chunk after the first is one entry.
    chunks = sessions_body.split("\n" + _ENTRY_BOUNDARY)
    # The first chunk may be a leading comment / blank — skip if it isn't an entry.
    for idx, chunk in enumerate(chunks):
        raw = chunk if (idx == 0 and chunk.startswith(_ENTRY_BOUNDARY)) else (
            _ENTRY_BOUNDARY + chunk if idx > 0 else chunk
        )
        if not raw.startswith(_ENTRY_BOUNDARY):
            continue
        first_line = raw.splitlines()[0]
        sid = first_line[len(_ENTRY_BOUNDARY):].split("·")[0].strip()
        entries.append((sid, raw.rstrip("\n")))
    return entries


def _render_session_entry(digest: SessionDigest) -> str:
    date_ist = digest.ended_at[:10]
    lines = [f"{_ENTRY_BOUNDARY}{digest.session_id} · {date_ist} · risk {digest.risk_tier_max}"]
    lines.append(f"<!-- ended:{digest.ended_at} -->")
    mood: list[str] = []
    if digest.mood_in is not None:
        mood.append(f"in {digest.mood_in}/10")
    if digest.mood_out is not None:
        mood.append(f"out {digest.mood_out}/10")
    lines.append("- mood: " + (" → ".join(mood) if mood else "not recorded"))
    if digest.techniques:
        lines.append("- techniques: " + ", ".join(
            f"{t.name} ({t.efficacy})" for t in digest.techniques))
    if digest.books_cited:
        lines.append("- books: " + ", ".join(digest.books_cited))
    if digest.threads_open:
        lines.append("- opened: " + "; ".join(digest.threads_open))
    if digest.threads_closed:
        lines.append("- closed: " + "; ".join(digest.threads_closed))
    if digest.homework_assigned:
        lines.append("- homework: " + "; ".join(digest.homework_assigned))
    if digest.key_insight:
        lines.append("- insight: " + digest.key_insight)
    if digest.generation_failed:
        lines.append("- ⚠ distillation failed — see the inbox digest / raw state.db for this session")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Open-threads folding
# ---------------------------------------------------------------------------


def _parse_thread_bullets(threads_body: str) -> list[str]:
    out: list[str] = []
    for line in threads_body.splitlines():
        m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if m:
            val = m.group(1).strip()
            if val and not val.startswith("_") and not val.startswith("("):
                out.append(val)
    return out


def _fold_open_threads(prior_open: list[str], digest: SessionDigest) -> list[str]:
    closed = {t.strip().lower() for t in digest.threads_closed}
    out: list[str] = []
    seen: set[str] = set()
    for t in prior_open + list(digest.threads_open):
        key = t.strip().lower()
        if not key or key in closed or key in seen:
            continue
        seen.add(key)
        out.append(t.strip())
    return out


# ---------------------------------------------------------------------------
# Homework rendering
# ---------------------------------------------------------------------------


def _render_homework(digest: SessionDigest, path: Path | None) -> str:
    """Homework from state.db (source of truth); fall back to the digest's assignments."""
    try:
        from dr_alex import statedb

        items = statedb.all_homework()
    except Exception:  # noqa: BLE001 — a broken store must never break the record
        items = []
    lines: list[str] = []
    if items:
        for h in items:
            box = "[x]" if h.status == "done" else ("[~]" if h.status == "dropped" else "[ ]")
            suffix = f"  (assigned {h.assigned_date})" if h.assigned_date else ""
            lines.append(f"- {box} {h.title}{suffix}")
    elif digest.homework_assigned:
        for title in digest.homework_assigned:
            lines.append(f"- [ ] {title}  (assigned {digest.ended_at[:10]})")
    else:
        lines.append("_No homework on the board._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assemble + write
# ---------------------------------------------------------------------------


def _iso(now: _dt.datetime) -> str:
    return timeutil.now_iso(now)


def _assemble(
    *,
    identity: str,
    patterns: str,
    session_entries: list[tuple[str, str]],
    homework: str,
    meds: str,
    open_threads: list[str],
    updated_ts: str,
) -> str:
    parts = [_FILE_HEADER, "\n# Dr. Alex Morgan — Active File\n"]
    parts.append(f"_Last updated: {updated_ts}_\n")
    parts.append(_H_IDENTITY + "\n" + identity.strip() + "\n")
    parts.append(_H_PATTERNS + "\n" + patterns.strip() + "\n")

    sess_body = "\n\n".join(entry for _sid, entry in session_entries) if session_entries else \
        "_No sessions logged yet._"
    parts.append(_H_SESSIONS + "\n" + sess_body + "\n")

    parts.append(_H_HOMEWORK + "\n" + homework.strip() + "\n")
    parts.append(_H_MEDS + "\n" + meds.strip() + "\n")

    threads_body = "\n".join(f"- {t}" for t in open_threads) if open_threads else \
        "_No open threads._"
    parts.append(_H_THREADS + "\n" + threads_body + "\n")

    return "\n".join(parts).rstrip("\n") + "\n"


def update_from_digest(
    digest: SessionDigest,
    *,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> Path:
    """Idempotently fold one finished session into the canonical Active File.

    Preserves the human-owned Identity / Living Pattern Docs / Medication sections; upserts
    the session-log entry (keyed by ``session_id``); rebuilds Homework from state.db; folds
    open threads. Returns the file path. Written locally FIRST (before any Notion mirror).
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p = active_file_path(path)
    existing = read_text(p) or ""
    sections = _split_sections(existing)

    identity = _section(sections, _H_IDENTITY, _DEFAULT_IDENTITY)
    patterns = _section(sections, _H_PATTERNS, _DEFAULT_PATTERNS_BODY)
    meds = _section(sections, _H_MEDS, _DEFAULT_MEDS_BODY)

    entries = _parse_session_entries(sections.get(_H_SESSIONS, ""))
    new_entry = _render_session_entry(digest)
    upserted = False
    for i, (sid, _text) in enumerate(entries):
        if sid == digest.session_id:
            entries[i] = (sid, new_entry)
            upserted = True
            break
    if not upserted:
        entries.insert(0, (digest.session_id, new_entry))  # newest first

    prior_open = _parse_thread_bullets(sections.get(_H_THREADS, ""))
    open_threads = _fold_open_threads(prior_open, digest)

    homework = _render_homework(digest, p)

    text = _assemble(
        identity=identity, patterns=patterns, session_entries=entries,
        homework=homework, meds=meds, open_threads=open_threads, updated_ts=_iso(now),
    )
    _write(p, text)
    return p


def ensure_scaffold(*, now: _dt.datetime | None = None, path: Path | None = None) -> Path:
    """Create the Active File with default sections if it doesn't exist yet."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p = active_file_path(path)
    if p.exists():
        return p
    text = _assemble(
        identity=_DEFAULT_IDENTITY, patterns=_DEFAULT_PATTERNS_BODY, session_entries=[],
        homework="_No homework on the board._", meds=_DEFAULT_MEDS_BODY,
        open_threads=[], updated_ts=_iso(now),
    )
    _write(p, text)
    return p
