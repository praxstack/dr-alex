"""`dr-alex` console entry point.

Modes
-----
    dr-alex               full warm session (Textual TUI)
    dr-alex checkin       gentle nightly "how was today?" opener (TUI)
    dr-alex "some text"   one-shot: a single safety-first exchange, printed and done
    dr-alex serve         run alexd (The Room) in the foreground — http://127.0.0.1:8787/
    dr-alex pair          mint a one-time pairing code for the PWA (single-use, ≤5min)
    dr-alex devices       list paired devices
    dr-alex revoke <id>   revoke a paired device token
    dr-alex books ingest  (re)build the book index from the corpus
    dr-alex books status  show the corpus manifest + index state
    dr-alex backup        G19 durability: git bundle + encrypted state.db snapshot
    dr-alex eval --once   G13 nightly eval (relative drift); normally run by the (disabled) cron
    dr-alex --card        print the crisis card (pure, no LLM) and exit
    dr-alex --version
"""

from __future__ import annotations

import sys

from dr_alex import __version__


def _backup_command() -> int:
    """`dr-alex backup` — G19 durability. Silent on success; prints only on failure."""
    from dr_alex import backup

    res = backup.run_backup()
    if res.ok:
        return 0  # silent-on-success (council + graft-pack G19)
    for err in res.errors or ["backup failed"]:
        print(f"backup error: {err}", file=sys.stderr)
    return 1


def _eval_command(args: list[str]) -> int:
    """`dr-alex eval --once` — run the G13 eval now (the launchd cron ships DISABLED)."""
    from dr_alex import eval_cron

    if "--once" not in args and args:
        print(f"Unknown eval args: {args}. Use: dr-alex eval --once", file=sys.stderr)
        return 2
    res = eval_cron.run_eval()
    if not res.ran:
        print("eval skipped (telemetry disabled).")
        return 0
    print(f"eval: scored {len(res.scored)} session(s).")
    for s in res.scored:
        print(f"  {s.session_id}: score={s.score:.1f}"
              + (f" z={s.z:.1f}" if s.z is not None else "")
              + (" [DRIFT]" if s.drift_flagged else ""))
    for alarm in res.drift_alarms:
        print(f"  drift: {alarm}", file=sys.stderr)
    if res.liveness_banner:
        print(f"  liveness: {res.liveness_banner}", file=sys.stderr)
    return 0


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


def _serve_command(args: list[str]) -> int:
    """`dr-alex serve` — run alexd (The Room) in the foreground. Loopback-only (D3 rider 1)."""
    from dr_alex import alexd

    host, port = alexd.HOST, alexd.PORT
    for a in args:
        if a.startswith("--port="):
            try:
                port = int(a.split("=", 1)[1])
            except ValueError:
                print(f"bad --port value: {a}", file=sys.stderr)
                return 2
        elif a.startswith("--host="):
            host = a.split("=", 1)[1]
    try:
        alexd.serve(host=host, port=port)
    except alexd.NonLoopbackBindRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


def _pair_command() -> int:
    """`dr-alex pair` — mint a one-time pairing code the PWA redeems for a device token."""
    from dr_alex import pairing

    code = pairing.create_pairing_code()
    print("Pairing code (valid ~5 minutes, single use):\n")
    print(f"    {code}\n")
    print("On the phone, open The Room and enter this code to pair the device.")
    return 0


def _devices_command() -> int:
    """`dr-alex devices` — list paired devices."""
    from dr_alex import pairing

    devices = pairing.list_devices()
    if not devices:
        print("No devices paired yet. Run: dr-alex pair")
        return 0
    for d in devices:
        state = "REVOKED" if d.revoked else "active"
        last = d.last_used_ts or "never"
        print(f"  {d.id}  [{state}]  {d.label!r}  last-used: {last}")
    return 0


def _revoke_command(args: list[str]) -> int:
    """`dr-alex revoke <device_id>` — revoke a paired device token."""
    from dr_alex import pairing

    if not args:
        print("Usage: dr-alex revoke <device_id>  (see: dr-alex devices)", file=sys.stderr)
        return 2
    ok = pairing.revoke_device(args[0])
    print("revoked." if ok else "no matching active device (already revoked, or bad id).",
          file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


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

    if args and args[0] == "serve":
        return _serve_command(args[1:])

    if args and args[0] == "pair":
        return _pair_command()

    if args and args[0] == "devices":
        return _devices_command()

    if args and args[0] == "revoke":
        return _revoke_command(args[1:])

    if args and args[0] == "books":
        return _books_command(args[1:])

    if args and args[0] == "backup":
        return _backup_command()

    if args and args[0] == "eval":
        return _eval_command(args[1:])

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
