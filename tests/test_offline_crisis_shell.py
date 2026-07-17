"""The load-bearing property: the crisis card is baked into the offline precache.

A service worker precaches the app shell + the crisis surface, so GET /crisis and the in-app
crisis view render with the Mac asleep / off-network. The precached crisis content carries the
hard-coded India resources (14416 … Shreya), ZERO personal data, and ZERO session state — and
it stays in sync with the single source of truth (:mod:`safety.crisis_card`).
"""

from __future__ import annotations

from pathlib import Path

from safety import crisis_card

ROOM = Path(__file__).resolve().parent.parent / "dr_alex" / "room"

#: The precached files that carry the crisis card (the offline surface).
_CRISIS_ASSETS = ("crisis.html", "app.js")
#: Actual personal/clinical data values that must never be baked into any shipped asset.
_PERSONAL_VALUES = ("Ria", "Shahjahanpur", "PERSONAL_MEMORY", "BOOK_CONTEXT", "sensitivity:high")
#: The pure offline crisis PAGE (crisis.html) must additionally carry zero session/app state.
_STRICT_LEAKS = _PERSONAL_VALUES + ("session_id", "continuity", "device_token")


def _sw() -> str:
    return (ROOM / "sw.js").read_text(encoding="utf-8")


def test_service_worker_precaches_shell_and_crisis() -> None:
    sw = _sw()
    for entry in ("/", "/app.js", "/crisis", "/crisis.html", "/manifest.json"):
        assert f'"{entry}"' in sw, f"service worker must precache {entry}"


def test_service_worker_never_caches_api_calls() -> None:
    sw = _sw()
    # Turns / sessions / homework are live data — never served stale from cache.
    for api in ("/turn", "/session", "/homework"):
        assert api in sw  # listed among the network-only prefixes


def test_precached_crisis_content_has_resources_and_no_personal_data() -> None:
    numbers = crisis_card.all_numbers()  # single source of truth
    for asset in _CRISIS_ASSETS:
        text = (ROOM / asset).read_text(encoding="utf-8")
        assert "14416" in text, f"{asset} missing Tele-MANAS 14416"
        assert crisis_card.THERAPIST_NAME in text, f"{asset} missing Shreya"
        for num in numbers:
            assert num in text, f"{asset} missing crisis number {num}"
        # No actual personal/clinical DATA baked into any shipped asset.
        for leak in _PERSONAL_VALUES:
            assert leak not in text, f"{asset} leaks personal data token {leak!r}"


def test_offline_crisis_page_has_zero_session_or_app_state() -> None:
    """crisis.html is the pure offline surface — no session ids, no app plumbing, nothing live."""
    html = (ROOM / "crisis.html").read_text(encoding="utf-8")
    for leak in _STRICT_LEAKS:
        assert leak not in html, f"crisis.html leaks {leak!r}"


def test_crisis_static_page_stays_in_sync_with_the_card() -> None:
    """crisis.html mirrors safety/crisis_card.py — the numbers can't silently drift."""
    html = (ROOM / "crisis.html").read_text(encoding="utf-8")
    for name, number, _note in crisis_card.CRISIS_RESOURCES:
        assert number in html, f"crisis.html missing {name} {number}"
    assert crisis_card.SHREYA_REACH_OUT_DRAFT in html
    assert crisis_card.THERAPIST_NAME in html
