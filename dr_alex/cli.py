"""`dr-alex` console entry point.

Modes
-----
    dr-alex               full warm session (Textual TUI)
    dr-alex checkin       gentle nightly "how was today?" opener (TUI)
    dr-alex "some text"   one-shot: a single safety-first exchange, printed and done
    dr-alex books ingest  (re)build the book index from the corpus
    dr-alex books status  show the corpus manifest + index state
    dr-alex --card        print the crisis card (pure, no LLM) and exit
    dr-alex --version
"""

from __future__ import annotations

import sys

from dr_alex import __version__


def _books_command(args: list[str]) -> int:
    """`dr-alex books ingest|status` — build / inspect the book RAG index."""
    from books import manifest
    from books import retriever

    sub = args[0] if args else "status"

    if sub == "ingest":
        print("Ingesting the book corpus into the FTS5/BM25 index…")
        stats = retriever.build_index()
        print(f"\nIndexed {stats.books_indexed} books, {stats.total_chunks} chunks.")
        for slug, n in stats.per_book.items():
            print(f"  {slug:28s} {n:>5d} chunks")
        for title, reason in stats.excluded:
            print(f"\n  WARNING — EXCLUDED (never indexed): {title}\n    reason: {reason}")
        print(f"\nIndex: {stats.index_path}")
        return 0

    if sub == "status":
        st = retriever.index_status()
        print("Corpus manifest:")
        for spec in manifest.included_books():
            print(f"  [included] {spec.slug:28s} {spec.title}")
        for spec in manifest.excluded_books():
            print(f"  [EXCLUDED] {spec.slug:28s} {spec.title}")
            print(f"             reason: {spec.exclusion_reason}")
        print()
        if st.exists:
            print(f"Index: {st.path}  ({st.total_chunks} chunks across {len(st.per_book)} books)")
        else:
            print(f"Index: {st.path}  — NOT BUILT. Run: dr-alex books ingest")
        return 0

    print(f"Unknown books subcommand: {sub!r}. Use 'ingest' or 'status'.", file=sys.stderr)
    return 2


def _print_oneshot(text: str) -> int:
    # Imported lazily so `--card` / `--version` don't pull in the model path.
    from dr_alex import engine
    from safety.triage import Tier

    tier, reply = engine.respond_oneshot(text)
    if tier is Tier.RED:
        # RED reply already contains the pure crisis card.
        print(reply)
    else:
        print(f"Alex ({tier.value.lower()}):\n{reply}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("--version", "-V"):
        print(f"dr-alex {__version__}")
        return 0

    if args and args[0] in ("--help", "-h"):
        print(__doc__)
        return 0

    if args and args[0] in ("--card", "--crisis", "--panic"):
        from safety import crisis_card

        print(crisis_card.render_text())
        return 0

    if args and args[0] == "books":
        return _books_command(args[1:])

    if not args:
        from dr_alex import app

        app.run("full")
        return 0

    if args[0] == "checkin" and len(args) == 1:
        from dr_alex import app

        app.run("checkin")
        return 0

    # Anything else: treat the joined arguments as a one-shot message.
    return _print_oneshot(" ".join(args))


if __name__ == "__main__":
    raise SystemExit(main())
