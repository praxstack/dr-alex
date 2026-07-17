"""R3 (binding): the per-turn trace is structured only — never a message body or book text."""

from __future__ import annotations

import logging

from dr_alex import engine, gates
from safety.triage import Tier


class _Chunk:
    def __init__(self, chunk_id: str, text: str) -> None:
        self.chunk_id = chunk_id
        self.text = text


def test_trace_is_structured_and_carries_no_content(caplog) -> None:
    chunks = [
        _Chunk("feeling-good:0044", "SECRET_BOOK_BODY_should_never_be_logged"),
        _Chunk("mindful-way:0077", "another SECRET_BOOK_BODY passage"),
    ]
    outcome = gates.GateOutcome(
        text="a reply containing SECRET_REPLY_CONTENT that must not be logged",
        dependency_action="regenerated",
        stripped_cites=["B9"],
        page_stripped=True,
    )
    with caplog.at_level(logging.INFO, logger="dr_alex.trace"):
        engine.trace_turn(Tier.AMBER, chunks, outcome)

    text = caplog.text
    # Structured facts are present…
    assert "AMBER" in text
    assert "feeling-good:0044" in text
    assert "mindful-way:0077" in text
    assert "regenerated" in text
    assert "B9" in text
    # …but no body content of any kind leaks.
    assert "SECRET_BOOK_BODY" not in text
    assert "SECRET_REPLY_CONTENT" not in text
