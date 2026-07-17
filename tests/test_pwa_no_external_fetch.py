"""The PWA is fully self-contained (council D6 spirit): ZERO external fetches.

No remote script/link/img/@import/webfont — every byte the phone loads is same-origin or an
inline ``data:`` URI, so The Room installs and runs with nothing but alexd on loopback.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOM = Path(__file__).resolve().parent.parent / "dr_alex" / "room"
ASSETS = ["index.html", "crisis.html", "app.css", "app.js", "sw.js", "manifest.json"]

# Absolute/protocol-relative URLs are external fetches — with two benign exceptions:
#   - the XML/SVG namespace http://www.w3.org/... (a namespace identifier, never fetched)
#   - loopback (127.0.0.1 / localhost), which is the local service itself
_URL_RE = re.compile(r"https?://[^\s\"')]+", re.IGNORECASE)
_PROTO_REL_RE = re.compile(r"(?<![:a-zA-Z0-9])//[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_ALLOW = ("http://www.w3.org", "https://www.w3.org", "http://127.0.0.1", "http://localhost")
_BANNED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.", "unpkg.com",
                 "jsdelivr.net", "cdnjs", "googleapis")


@pytest.mark.parametrize("name", ASSETS)
def test_no_external_absolute_urls(name: str) -> None:
    text = (ROOM / name).read_text(encoding="utf-8")
    offenders = [u for u in _URL_RE.findall(text) if not u.startswith(_ALLOW)]
    assert offenders == [], f"{name} references external URLs: {offenders}"
    assert _PROTO_REL_RE.search(text) is None, f"{name} has a protocol-relative (external) URL"


@pytest.mark.parametrize("name", ASSETS)
def test_no_cdn_or_webfont_hosts(name: str) -> None:
    text = (ROOM / name).read_text(encoding="utf-8").lower()
    for host in _BANNED_HOSTS:
        assert host not in text, f"{name} references banned external host {host!r}"
    assert "@import" not in text, f"{name} uses @import (potential external fetch)"


def test_html_asset_refs_are_local_or_data_uris() -> None:
    html = (ROOM / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    assert refs, "expected some src/href refs in the shell"
    for ref in refs:
        assert ref.startswith(("/", "data:", "#", "tel:")), f"non-local ref in index.html: {ref}"


def test_no_font_face_with_remote_src() -> None:
    css = (ROOM / "app.css").read_text(encoding="utf-8")
    # No @font-face at all (system font stack only) → nothing to fetch.
    assert "@font-face" not in css
