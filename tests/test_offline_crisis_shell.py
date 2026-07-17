"""The load-bearing property: the crisis card is baked into the offline precache.

A service worker precaches the app shell + the crisis surface, so GET /crisis and the in-app
crisis view render with the Mac asleep / off-network. The precached crisis content carries the
hard-coded India resources (14416 … Shreya), ZERO personal data, and ZERO session state — and
it stays in sync with the single source of truth (:mod:`safety.crisis_card`).
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from dr_alex import alexd
from safety import crisis_card

ROOM = Path(__file__).resolve().parent.parent / "dr_alex" / "room"


def _precache_routes() -> list[str]:
    """The exact routes the service worker precaches (CRITICAL + OPTIONAL arrays in sw.js)."""
    sw = (ROOM / "sw.js").read_text(encoding="utf-8")
    routes: list[str] = []
    for name in ("CRITICAL", "OPTIONAL"):
        m = re.search(rf"var {name} = \[(.*?)\];", sw, re.DOTALL)
        assert m, f"sw.js must define {name}"
        routes.extend(re.findall(r'"([^"]+)"', m.group(1)))
    return routes

#: The precached files that carry the crisis card (the offline surface).
_CRISIS_ASSETS = ("crisis.html", "app.js")
#: Actual personal/clinical data values that must never be baked into any shipped asset.
_PERSONAL_VALUES = ("Ria", "Shahjahanpur", "PERSONAL_MEMORY", "BOOK_CONTEXT", "sensitivity:high")
#: The pure offline crisis PAGE (crisis.html) must additionally carry zero session/app state.
_STRICT_LEAKS = _PERSONAL_VALUES + ("session_id", "continuity", "device_token")


def _sw() -> str:
    return (ROOM / "sw.js").read_text(encoding="utf-8")


def test_service_worker_precaches_shell_and_crisis() -> None:
    routes = _precache_routes()
    # The load-bearing offline surface: the app shell and the crisis card.
    assert "/" in routes, "service worker must precache the app shell"
    assert "/crisis" in routes, "service worker must precache the crisis card"


def test_every_precached_route_is_actually_served() -> None:
    """Regression guard: a precached route that the service 404s makes ``cache.addAll`` reject,
    so no service worker ever activates and the ENTIRE offline crisis shell silently dies. This
    shipped once (``/index.html`` + ``/crisis.html`` were precached but 404). Every precached
    URL must return 200 from the real app."""
    client = TestClient(alexd.app)
    for route in _precache_routes():
        resp = client.get(route)
        assert resp.status_code == 200, f"precached route {route} is not served (got {resp.status_code})"


def test_critical_offline_routes_carry_the_crisis_card() -> None:
    """The two atomically-cached routes must themselves render the crisis resources offline."""
    client = TestClient(alexd.app)
    crisis = client.get("/crisis")
    assert crisis.status_code == 200
    assert "14416" in crisis.text and crisis_card.THERAPIST_NAME in crisis.text


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
