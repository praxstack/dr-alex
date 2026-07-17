"""The gated operations (book_search + gated recall) refuse without a valid token (D3)."""

from __future__ import annotations

import logging

import pytest

from dr_alex import captoken, engine, memstore


class _FakeRetriever:
    def __init__(self):
        self.calls = 0

    def retrieve(self, text, k=4):
        self.calls += 1

        class _Chunk:
            book_title, chapter, chunk_id, text = "B", None, "c:1", "body"
        return [_Chunk()]


def test_book_search_refused_without_token(caplog) -> None:
    r = _FakeRetriever()
    with caplog.at_level(logging.WARNING, logger="dr_alex.trace"):
        retrieved, ctx = engine.retrieve_context("how do I reframe a thought", retriever=r)
    assert retrieved == [] and ctx is None
    assert r.calls == 0                     # the retriever was never even consulted
    assert "refused" in caplog.text.lower()


def test_book_search_works_within_grant() -> None:
    r = _FakeRetriever()
    with captoken.granted():
        retrieved, ctx = engine.retrieve_context("how do I reframe a thought", retriever=r)
    assert r.calls == 1
    assert retrieved and ctx is not None


def test_gated_recall_refused_without_token(monkeypatch, caplog) -> None:
    monkeypatch.setenv("DR_ALEX_MEMORY_OFF", "0")

    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("recall must not spawn memctl without a capability token")

    monkeypatch.setattr(memstore, "_run", boom)
    with caplog.at_level(logging.WARNING, logger="dr_alex.memstore"):
        assert memstore.recall("anything") == []
    assert "refused" in caplog.text.lower()


def test_expired_token_refuses_recall(monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_MEMORY_OFF", "0")

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("expired token must not authorize recall")

    monkeypatch.setattr(memstore, "_run", boom)
    # Mint a token then let it expire by pinning verify's clock into the future.
    tok = captoken.mint(1, now=0.0)
    reset = captoken._current.set(tok)
    try:
        # verify() uses time.time(); the token minted at t=0 with ttl=1 is long expired now.
        with pytest.raises(captoken.CapabilityRefused):
            captoken.require()
    finally:
        captoken._current.reset(reset)
