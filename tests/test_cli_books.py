"""`dr-alex books ingest|status` CLI wiring."""

from __future__ import annotations

from dr_alex import cli


def test_books_status_prints_manifest(capsys) -> None:
    rc = cli.main(["books", "status"])
    out = capsys.readouterr().out
    assert rc == 0
    # 13 included + the excluded Beck book, clearly labeled.
    assert out.count("[included]") == 13
    assert "[EXCLUDED]" in out
    assert "Cognitive Therapy of Depression" in out
    assert "Index:" in out


def test_books_ingest_routes_to_build(monkeypatch, capsys) -> None:
    from books import retriever
    from pathlib import Path

    called = {"n": 0}

    def fake_build():
        called["n"] += 1
        return retriever.IngestStats(
            index_path=Path("/tmp/x/books.db"),
            per_book={"feeling-good": 5},
            total_chunks=5,
            excluded=[("Cognitive Therapy of Depression", "broken extraction")],
            warned_excluded=True,
        )

    monkeypatch.setattr(retriever, "build_index", fake_build)
    rc = cli.main(["books", "ingest"])
    out = capsys.readouterr().out
    assert rc == 0
    assert called["n"] == 1
    assert "Indexed 1 books" in out
    assert "EXCLUDED" in out and "Cognitive Therapy of Depression" in out


def test_books_unknown_subcommand(capsys) -> None:
    rc = cli.main(["books", "frobnicate"])
    assert rc == 2
