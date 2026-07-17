"""G16 wire-decision audit + empty-output guard (R3: structured, body-free)."""

from __future__ import annotations

import logging

from dr_alex import wire
from safety.triage import Tier


def test_audit_line_is_structured_and_body_free(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="dr_alex.wire"):
        wire.audit_turn(
            tier=Tier.AMBER,
            safety_path_taken="probe-asked",
            chunk_ids=["feeling-good:0044", "mindful-way:0077"],
            memory_ids=["01JMEM0001"],
        )
    text = caplog.text
    # Structural facts present…
    assert "AMBER" in text
    assert "probe-asked" in text
    assert "feeling-good:0044" in text
    assert "01JMEM0001" in text
    # …and nothing that could carry a body: the audit call is given no message/reply at all,
    # so there is nothing to leak. Sanity-check the field set is exactly the G16 contract.
    assert "tier=" in text and "safety=" in text and "chunk_ids=" in text and "memory_ids=" in text


def test_empty_output_guard_substitutes_calm_fallback() -> None:
    for empty in ("", "   ", "\n\n", "(no response)"):
        text, was_empty = wire.empty_output_guard(empty)
        assert was_empty is True
        assert text == wire.EMPTY_REPLY_FALLBACK
        assert text.strip()  # never itself empty


def test_empty_output_guard_passes_through_real_replies() -> None:
    text, was_empty = wire.empty_output_guard("Here's a small next step you could try.")
    assert was_empty is False
    assert text == "Here's a small next step you could try."
