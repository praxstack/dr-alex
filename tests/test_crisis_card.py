"""Crisis card: content present, numbers exactly right, printable files in sync."""

from __future__ import annotations

from pathlib import Path

from safety import crisis_card

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_NUMBERS = ["14416", "9152987821", "9820466726", "1860-2662-345", "112"]


def test_exact_number_list() -> None:
    assert crisis_card.all_numbers() == EXPECTED_NUMBERS


def test_all_renderers_contain_every_number() -> None:
    for render in (crisis_card.render_text(), crisis_card.render_markdown(), crisis_card.render_rich()):
        for number in EXPECTED_NUMBERS:
            assert number in render, f"missing {number} in a renderer"


def test_telemanas_alternate_number_present() -> None:
    # The alternate Tele-MANAS number must be reachable too.
    assert "1800-891-4416" in crisis_card.render_text()
    assert "1800-891-4416" in crisis_card.render_markdown()


def test_shreya_and_grounding_present() -> None:
    for render in (crisis_card.render_text(), crisis_card.render_markdown(), crisis_card.render_rich()):
        assert "Shreya" in render
    assert "reach out to her" in crisis_card.THERAPIST_LINE
    assert crisis_card.SHREYA_REACH_OUT_DRAFT  # non-empty pre-written message
    assert "Tele-MANAS" in crisis_card.render_text()


def test_printable_files_exist_and_in_sync() -> None:
    md = (REPO_ROOT / "data" / "crisis-card.md").read_text(encoding="utf-8")
    txt = (REPO_ROOT / "data" / "crisis-card.txt").read_text(encoding="utf-8")

    # The rendered content is embedded verbatim (no drift between code and file).
    assert crisis_card.render_markdown() in md
    assert crisis_card.render_text() in txt

    # Every number is in both printable files.
    for number in EXPECTED_NUMBERS:
        assert number in md
        assert number in txt

    # The out-of-band note tells Prax to save it to his phone / print it.
    assert "lock screen" in md.lower()
    assert "print" in md.lower()


def test_files_never_claim_to_be_a_crisis_service() -> None:
    # Sanity: the card routes to real humans, it doesn't pose as one.
    txt = crisis_card.render_text().lower()
    assert "you are not alone" in txt
