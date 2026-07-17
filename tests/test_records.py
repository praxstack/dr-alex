"""The canonical Active File (council D4): perms, idempotent session log, pattern parsing."""

from __future__ import annotations

import datetime as _dt
import os
import stat

from dr_alex import records, statedb
from dr_alex.digest import SessionDigest, Technique

_UTC = _dt.timezone.utc


def _now(h: int = 9) -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, h, 0, tzinfo=_UTC)


def _digest(**over) -> SessionDigest:
    base = dict(
        session_id="01SESSONE", started_at="2026-07-18T08:00:00Z",
        ended_at="2026-07-18T09:00:00Z", risk_tier_max="GREEN",
        mood_in=4, mood_out=6,
        techniques=[Technique("behavioral-activation", "helped")],
        threads_open=["the swim re-entry"], key_insight="Small steps beat heroic leaps.",
        last_topic="morning activation",
    )
    base.update(over)
    return SessionDigest(**base)


def test_scaffold_creates_file_with_locked_down_perms() -> None:
    p = records.ensure_scaffold(now=_now())
    assert p.exists()
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700
    text = p.read_text(encoding="utf-8")
    # The human-readable canonical sections + the PraxVault migration note are present.
    for section in ("## Identity", "## Living Pattern Docs", "## Session Log",
                    "## Homework", "## Medication Timeline", "## Open Threads"):
        assert section in text
    assert "PraxVault migration" in text


def test_update_from_digest_is_idempotent_by_session_id() -> None:
    p = records.update_from_digest(_digest(), now=_now())
    text1 = p.read_text(encoding="utf-8")
    assert text1.count("### session 01SESSONE") == 1
    assert "Small steps beat heroic leaps." in text1

    # Replaying the SAME session (idempotent crash-recovery) must NOT duplicate the entry.
    records.update_from_digest(_digest(key_insight="Updated insight."), now=_now(10))
    text2 = p.read_text(encoding="utf-8")
    assert text2.count("### session 01SESSONE") == 1
    assert "Updated insight." in text2
    assert "Small steps beat heroic leaps." not in text2

    # A different session adds a second entry (newest first).
    records.update_from_digest(_digest(session_id="01SESSTWO"), now=_now(11))
    text3 = p.read_text(encoding="utf-8")
    assert text3.count("### session ") == 2
    assert text3.index("01SESSTWO") < text3.index("01SESSONE")  # newest first


def test_open_threads_fold_open_minus_closed() -> None:
    records.update_from_digest(_digest(session_id="01A", threads_open=["thread A", "thread B"]),
                               now=_now())
    p = records.update_from_digest(
        _digest(session_id="01B", threads_open=["thread C"], threads_closed=["thread A"]),
        now=_now(10),
    )
    text = p.read_text(encoding="utf-8")
    threads = text.split("## Open Threads", 1)[1]
    assert "thread B" in threads
    assert "thread C" in threads
    assert "thread A" not in threads  # closed → folded out


def test_homework_rendered_from_statedb_source_of_truth() -> None:
    statedb.add_homework("walk 15 min before standup", source_session="01A")
    p = records.update_from_digest(_digest(), now=_now())
    text = p.read_text(encoding="utf-8")
    hw = text.split("## Homework", 1)[1].split("## Medication", 1)[0]
    assert "walk 15 min before standup" in hw
    assert "[ ]" in hw  # open homework checkbox


def test_pattern_docs_parse_names_and_aliases() -> None:
    p = records.ensure_scaffold(now=_now())
    scaffold = p.read_text(encoding="utf-8")
    # Inject two named living-pattern docs by hand (human-owned section).
    patterns_block = (
        "## Living Pattern Docs\n"
        "### Rumination Loop\n"
        "aliases: doomscroll, 3am scroll\n"
        "Circling the same worry at night.\n\n"
        "### Avoidance\n"
        "Putting off the thing that matters.\n"
    )
    edited = scaffold.replace(
        scaffold.split("## Living Pattern Docs", 1)[1].split("## Session Log", 1)[0],
        "\n" + patterns_block.split("## Living Pattern Docs", 1)[1] + "\n",
    )
    p.write_text(edited, encoding="utf-8")

    docs = records.parse_pattern_docs(p.read_text(encoding="utf-8"))
    names = {d.name for d in docs}
    assert names == {"Rumination Loop", "Avoidance"}
    rumination = next(d for d in docs if d.name == "Rumination Loop")
    assert "doomscroll" in rumination.aliases
    assert "3am scroll" in rumination.aliases


def test_human_owned_sections_survive_update() -> None:
    p = records.ensure_scaffold(now=_now())
    text = p.read_text(encoding="utf-8")
    text = text.replace("### Avoidance", "").replace(
        "_No named patterns yet — Prax and Shreya name them here as they emerge._",
        "### Rumination Loop\naliases: doomscroll\nCircling a worry.\n",
    )
    p.write_text(text, encoding="utf-8")
    # An automated session update must preserve the hand-authored pattern doc verbatim.
    records.update_from_digest(_digest(), now=_now(10))
    after = p.read_text(encoding="utf-8")
    assert "### Rumination Loop" in after
    assert "Circling a worry." in after
