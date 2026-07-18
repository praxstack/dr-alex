"""G11 — the Friday Shreya-prep packet (adapted from the graft-pack clinician digest).

A LOCAL-ONLY, deterministic pre-session brief for Shreya (Prax's therapist). It is generated
from already-stored telemetry (the ``state.db`` window snapshot) and the named living pattern
docs in the canonical Active File. It is **never sent** — release to a real clinician is an
explicit, manual, Prax-driven act (mirrors the graft-pack sample's Phase-5 invariant).

Design choices carried from the graft-pack + the Hermes "what went wrong" list:
  * **No silent failures.** 24/36 Hermes digests failed silently. Here, if generation cannot
    complete, we emit a LOUD ``GENERATION FAILED`` placeholder that points at the raw data
    paths so a human can drill in (never an empty or missing file).
  * **Named patterns, including the ones that did NOT appear.** For each living pattern doc we
    report whether it surfaced this window; the null cases carry the explicit caution to
    "probe directly rather than trusting the null flag."
  * **Test-traffic caution (G9).** Synthetic/test turns are counted and flagged separately so a
    QA smoke run is never mistaken for a clinical signal.
  * **The G18 dependency signal.** Late-night clustering is surfaced gently in its own line.

This module makes NO model call — it is a pure report over structured data, so it never
touches the single LLM entrypoint.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dr_alex import config, records, statedb, timeutil
from dr_alex.records import PatternDoc
from dr_alex.statedb import WindowSnapshot

_BANNER = (
    "# LOCAL DRAFT ONLY — NOT SENT\n\n"
    "This is a local pre-session brief for Shreya, generated from Dr. Alex's between-visits\n"
    "telemetry. Dr. Alex does **not** send, upload, or share it. Handing it to Shreya is an\n"
    "explicit, manual act by Prax. All pattern language reflects Prax's self-report and observed\n"
    "agent interaction, **not** a diagnosis. Medication and risk determinations remain Shreya's.\n"
)


# ---------------------------------------------------------------------------
# Pattern-appearance detection (deterministic, over the in-memory corpus)
# ---------------------------------------------------------------------------


@dataclass
class PatternHit:
    name: str
    appeared: bool
    mentions: int


def _match_pattern(doc: PatternDoc, corpus: list[str]) -> PatternHit:
    needles = [doc.name] + list(doc.aliases)
    patterns = [re.compile(re.escape(n), re.IGNORECASE) for n in needles if n.strip()]
    mentions = 0
    for text in corpus:
        if any(p.search(text) for p in patterns):
            mentions += 1
    return PatternHit(name=doc.name, appeared=mentions > 0, mentions=mentions)


def detect_patterns(docs: list[PatternDoc], corpus: list[str]) -> list[PatternHit]:
    return [_match_pattern(d, corpus) for d in docs]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _mood_phrase(s) -> str:
    if s.open_mood is not None and s.close_mood is not None:
        return f"{s.open_mood}→{s.close_mood}/10"
    if s.open_mood is not None:
        return f"{s.open_mood}/10 (open)"
    if s.close_mood is not None:
        return f"{s.close_mood}/10 (close)"
    return "not recorded"


def _headline(snap: WindowSnapshot) -> str:
    real = snap.real_sessions
    n = len(real)
    if n == 0:
        return (
            "No real Dr. Alex check-ins this window. That absence is itself a signal worth a "
            "gentle probe (avoidance, a good stretch, or simply busy?)."
        )
    risk = snap.risk_tier_max or "GREEN"
    late = snap.late_night.late_night_count if snap.late_night else 0
    late_bit = (f" {late} started late at night (00:00–05:00 IST)." if late else "")
    return (
        f"{n} real check-in{'s' if n != 1 else ''} this window; max automated risk tier "
        f"{risk}.{late_bit} Details and the named-pattern read follow."
    )


def build_packet(
    snap: WindowSnapshot,
    docs: list[PatternDoc],
    *,
    now: _dt.datetime,
    state_db_path: str | None = None,
    active_file_path: str | None = None,
) -> str:
    """Render the packet markdown from a window snapshot + the named living pattern docs."""
    generated = _iso(now)
    hits = detect_patterns(docs, snap.pattern_corpus)
    appeared = [h for h in hits if h.appeared]
    absent = [h for h in hits if not h.appeared]

    out: list[str] = [_BANNER]
    out.append(
        f"**Generated:** {generated}  \n"
        f"**Window:** {snap.from_ts} → {snap.to_ts} ({snap.window_days}-day rollup)  \n"
        f"**Visibility:** local file only (mode 0o600) — for Prax to review, then hand to Shreya."
    )
    out.append("\n---\n")

    out.append("## Headline\n\n" + _headline(snap))

    # -- Patterns surfaced + the explicit null cases ----------------------
    out.append("## Patterns Surfaced (named living pattern docs)")
    if not docs:
        out.append(
            "_No named patterns are defined in the Active File yet. Name them under "
            "`## Living Pattern Docs` so this section can track which do and don't recur._"
        )
    else:
        if appeared:
            out.append("**Surfaced this window:**")
            out.append("\n".join(
                f"- **{h.name}** — matched in {h.mentions} window entr"
                f"{'y' if h.mentions == 1 else 'ies'}." for h in appeared))
        else:
            out.append("**Surfaced this window:** none of the named patterns matched.")
        if absent:
            out.append(
                "**Did NOT surface this window** (probe directly rather than trusting the null "
                "flag — the matcher only sees named/aliased phrasings):")
            out.append("\n".join(f"- {h.name}" for h in absent))

    # -- Self-reported state (mood rollup) --------------------------------
    out.append("## Self-Reported State (mood chips)")
    real = snap.real_sessions
    if real:
        rows = ["| date | mood (in→out) |", "|---|---|"]
        for s in real:
            rows.append(f"| {s.date_ist} | {_mood_phrase(s)} |")
        out.append("\n".join(rows))
    else:
        out.append("_No real sessions with mood chips this window._")
    open_hw = [h for h in snap.homework if h.status == "open"]
    if open_hw:
        out.append("**Homework still open:** " + "; ".join(h.title for h in open_hw))

    # -- Behavioral signals (with the test-traffic caution) ---------------
    out.append("## Behavioral Signals (no diagnosis)")
    sig_lines = [
        f"- Sessions this window: {len(snap.sessions)} total "
        f"({len(real)} real, {len(snap.sessions) - len(real)} test/QA).",
        f"- Turns: {snap.turns_total} total; {snap.turns_flagged} carried a non-clean safety / "
        f"dependency / register action.",
    ]
    if snap.turns_test_traffic:
        sig_lines.append(
            f"- ⚠ Test-traffic caution (G9): {snap.turns_test_traffic} turn(s) were synthetic / "
            "QA traffic and are NOT a clinical signal — do not read them as mood.")
    if snap.late_night and snap.late_night.late_night_count:
        s = snap.late_night
        flagged = " — clustering flagged (G18)" if s.flagged else ""
        sig_lines.append(
            f"- Late-night dependency signal (G18): {s.late_night_count} session(s) started "
            f"00:00–05:00 IST over {s.window_days}d (threshold {s.threshold}){flagged}.")
    tier_bits = ", ".join(f"{k}:{v}" for k, v in sorted(snap.tier_counts.items()))
    if tier_bits:
        sig_lines.append(f"- Automated risk-tier distribution: {tier_bits}.")
    out.append("\n".join(sig_lines))

    # -- What Shreya should probe -----------------------------------------
    out.append("## What Shreya Should Probe")
    probes: list[str] = []
    if snap.risk_tier_max == "RED":
        probes.append(
            "A RED crisis tier fired this window — do a **direct** in-session safety check; "
            "the automated card is a floor, not a substitute for your read.")
    if snap.late_night and snap.late_night.flagged:
        probes.append(
            "Late-night check-in clustering — explore sleep and what the 3 AM sittings are "
            "reaching for.")
    if absent:
        probes.append(
            "The named patterns that did NOT surface (above) — confirm directly; the null flag "
            "only means the matcher didn't see the phrasing, not that the pattern is dormant.")
    if open_hw:
        probes.append("Follow up on the still-open homework listed above.")
    if not probes:
        probes.append(
            "Nothing automated flagged this window — use your own read; a quiet log is not the "
            "same as a quiet week.")
    out.append("\n".join(f"{i}. {p}" for i, p in enumerate(probes, 1)))

    # -- Data sources (so Shreya/Prax can drill in) -----------------------
    out.append("## Data Sources")
    out.append(
        f"- Telemetry: `{state_db_path or statedb.state_db_path()}` "
        f"(encrypted at rest; decrypted in-process only)\n"
        f"- Canonical record: `{active_file_path or config.active_file_path()}`\n"
        f"- This packet is generated locally and never transmitted."
    )

    return "\n\n".join(out).rstrip() + "\n"


def _fail_loud(now: _dt.datetime, reason: str, window_days: int) -> str:
    """The LOUD placeholder — never a silent or empty digest (Hermes anti-pattern #1/#3)."""
    return (
        _BANNER
        + "\n\n"
        + f"# ⚠ PACKET GENERATION FAILED — {_iso(now)}\n\n"
        + f"The Friday Shreya-prep packet could not be generated: `{reason}`.\n\n"
        + "This is a LOUD placeholder (a Hermes-era lesson: 24/36 digests once failed silently). "
        + "Review the raw data directly:\n\n"
        + f"- Telemetry (encrypted): `{statedb.state_db_path()}`\n"
        + f"- Canonical record: `{config.active_file_path()}`\n"
        + f"- Window requested: last {window_days} day(s).\n"
    )


# ---------------------------------------------------------------------------
# Orchestration + write-out
# ---------------------------------------------------------------------------


@dataclass
class PacketResult:
    ok: bool
    text: str
    out_path: str | None = None


def _iso(now: _dt.datetime) -> str:
    return timeutil.now_iso(now)


def packet_dir() -> Path:
    return config.records_dir() / "shreya-prep"


def generate(
    *,
    now: _dt.datetime | None = None,
    window_days: int = 7,
    write: bool = True,
    state_path: Path | None = None,
    active_path: Path | None = None,
) -> PacketResult:
    """Build (and optionally write) the packet. Fail-loud: always returns SOME text."""
    now = now or _dt.datetime.now(_dt.UTC)
    try:
        snap = statedb.window_snapshot(now=now, window_days=window_days, path=state_path)
        docs = records.parse_pattern_docs(records.read_text(active_path))
        text = build_packet(
            snap, docs, now=now,
            state_db_path=str(state_path) if state_path else None,
            active_file_path=str(active_path) if active_path else None,
        )
        ok = True
    except Exception as exc:  # noqa: BLE001 — never fail silently; emit the loud placeholder
        text = _fail_loud(now, type(exc).__name__, window_days)
        ok = False

    out_path = None
    if write:
        out_path = _write_packet(text, now)
    return PacketResult(ok=ok, text=text, out_path=out_path)


def _write_packet(text: str, now: _dt.datetime) -> str:
    d = packet_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    # Filename = date only, never clinical content (mirrors the D6 export-filename rule).
    p = d / f"shreya-prep-{now.astimezone(_dt.UTC).strftime('%Y-%m-%d')}.md"
    p.write_text(text, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return str(p)
