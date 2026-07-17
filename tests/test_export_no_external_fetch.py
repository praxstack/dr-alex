"""Council D6 rider 1: the exported HTML makes ZERO external fetches.

A stray font CDN / remote image / @import in a print-to-PDF export is an egress beacon — the
generated HTML must be fully self-contained (inline CSS, inline SVG, system fonts, data: URIs
only). This test renders a *full* export (the most content-rich path) and scans it.
"""

from __future__ import annotations

import datetime as _dt
import re

from dr_alex import export, records, statedb
from dr_alex.digest import SessionDigest, Technique

_UTC = _dt.timezone.utc

# Absolute/protocol-relative URLs are external fetches — with two benign exceptions mirroring
# the PWA test: the SVG/XML namespace (never fetched) and loopback (the local service itself).
_URL_RE = re.compile(r"https?://[^\s\"')]+", re.IGNORECASE)
_PROTO_REL_RE = re.compile(r"(?<![:a-zA-Z0-9])//[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_ALLOW = ("http://www.w3.org", "https://www.w3.org", "http://127.0.0.1", "http://localhost")
_BANNED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.", "unpkg.com",
                 "jsdelivr.net", "cdnjs", "googleapis")


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 12, 0, tzinfo=_UTC)


def _full_html() -> str:
    # Seed some content so the full export is non-trivial (homework, insight, mood, risk).
    statedb.record_mood("open", 4, session_id="01A", now=_dt.datetime(2026, 7, 15, 8, tzinfo=_UTC))
    statedb.add_homework("call Shreya about sleep", now=_dt.datetime(2026, 7, 15, 8, tzinfo=_UTC))
    records.update_from_digest(SessionDigest(
        session_id="01A", started_at="2026-07-16T08:00:00Z", ended_at="2026-07-16T09:00:00Z",
        risk_tier_max="AMBER", key_insight="an insight worth keeping",
        techniques=[Technique("grounding", "helped")],
    ), now=_dt.datetime(2026, 7, 16, 9, tzinfo=_UTC))
    res = export.export_range("2026-07-01", "2026-07-18", redaction="full", now=_now(), write=False)
    return res.html


def test_export_html_has_no_external_absolute_urls() -> None:
    html = _full_html()
    offenders = [u for u in _URL_RE.findall(html) if not u.startswith(_ALLOW)]
    assert offenders == [], f"export HTML references external URLs: {offenders}"
    assert _PROTO_REL_RE.search(html) is None, "export HTML has a protocol-relative (external) URL"


def test_export_html_has_no_cdn_or_webfont_hosts() -> None:
    html = _full_html().lower()
    for host in _BANNED_HOSTS:
        assert host not in html, f"export HTML references banned external host {host!r}"
    assert "@import" not in html, "export HTML uses @import (potential external fetch)"
    assert "@font-face" not in html, "export HTML declares @font-face (potential webfont fetch)"


def test_export_html_has_no_remote_script_or_img() -> None:
    html = _full_html()
    # No <script> at all (a print-to-PDF page needs none) and no external <img src>.
    assert "<script" not in html.lower()
    for ref in re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html):
        assert ref.startswith(("data:", "#", "/", "tel:")), f"non-local ref in export HTML: {ref}"
