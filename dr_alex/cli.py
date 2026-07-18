"""`dr-alex` console entry point.

Modes
-----
    dr-alex               full warm session (Textual TUI)
    dr-alex checkin       gentle nightly "how was today?" opener (TUI)
    dr-alex checkin --notify   post the FIXED nightly notification (what the launchd job runs)
    dr-alex export --from <date> --to <date> [--redaction summary|full]
                          date-ranged markdown + self-contained HTML (print-to-PDF)
    dr-alex review        a default last-30-days export, ready to print-to-PDF
    dr-alex "some text"   one-shot: a single safety-first exchange, printed and done
    dr-alex serve         run alexd (The Room) in the foreground — http://127.0.0.1:8787/
    dr-alex pair          mint a one-time pairing code for the PWA (single-use, ≤5min)
    dr-alex devices       list paired devices
    dr-alex revoke <id>   revoke a paired device token
    dr-alex books ingest  (re)build the book index from the corpus
    dr-alex books status  show the corpus manifest + index state
    dr-alex backup        G19 durability: git bundle + encrypted state.db snapshot
    dr-alex eval --once   G13 nightly eval (relative drift); normally run by the (disabled) cron
    dr-alex improve --once [--dry-run]
                          G22 nightly persona keep-or-revert loop (propose→gate→benchmark→keep)
    dr-alex improve status   history + last decision of the self-improvement loop
    dr-alex improve revert   undo the last ACCEPTED persona change (git revert)
    dr-alex shreya        G11 Friday Shreya-prep packet (local draft; never sent)
    dr-alex records       show the canonical Active File path (creating the scaffold if needed)
    dr-alex notion status show whether the Notion mirror is enabled (secrets stay in Keychain)
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


def _improve_command(args: list[str]) -> int:
    """`dr-alex improve --once [--dry-run] | status | revert` — the G22 keep-or-revert loop.

    The launchd job (``tools/launchd/com.dr-alex.improve.plist``) ships DISABLED and needs
    ``claude`` auth (unavailable from launchd), so this only ever runs when *you* invoke it.
    """
    from dr_alex import improve

    sub = args[0] if args else "--once"

    if sub == "status":
        runs = improve.history()
        if not runs:
            print("improve: no runs yet. Try: dr-alex improve --once --dry-run")
            return 0
        last = runs[-1]
        keeps = sum(1 for r in runs if r.get("decision") == "keep" and not r.get("dry_run"))
        print(f"improve history: {len(runs)} run(s), {keeps} accepted change(s).")
        print(f"last decision: {last.get('decision')} — {last.get('reason')}")
        if last.get("candidate_summary"):
            print(f"  candidate: {last['candidate_summary']}")
        sg = last.get("safety_gate", {})
        print(f"  safety gate passed: {sg.get('passed')}  "
              f"(golden RED sensitivity: {sg.get('golden_red_sensitivity')})")
        print(f"  WAI-SR baseline→candidate: {last.get('wai_sr_baseline')} → "
              f"{last.get('wai_sr_candidate')}")
        if last.get("commit_sha"):
            print(f"  commit: {last['commit_sha']}")
        return 0

    if sub == "revert":
        ok, msg = improve.revert_last()
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    if sub == "--once":
        dry = "--dry-run" in args
        try:
            res = improve.run_once(dry_run=dry)
        except improve.ImproveError as exc:
            print(f"improve error: {exc}", file=sys.stderr)
            return 1
        tag = " [DRY-RUN]" if res.dry_run else ""
        print(f"improve{tag}: {res.decision.upper()} — {res.reason}")
        if res.summary:
            print(f"  candidate: {res.summary}")
        failed = [k for k, v in res.invariants.items() if not v]
        print(f"  frozen invariants: {'all intact' if not failed else 'MISSING ' + ', '.join(failed)}"
              f"  |  golden RED sensitivity: {res.golden_sensitivity}")
        print(f"  WAI-SR baseline→candidate: {res.baseline_mean} → {res.candidate_mean}")
        if res.commit_sha:
            print(f"  committed: {res.commit_sha}")
        return 0

    print(f"Unknown improve subcommand: {sub!r}. Use '--once [--dry-run]', 'status', or 'revert'.",
          file=sys.stderr)
    return 2


def _books_command(args: list[str]) -> int:
    """`dr-alex books ingest|status|add` — build / inspect / grow the book RAG index."""
    from books import manifest
    from books import retriever

    sub = args[0] if args else "status"

    if sub == "add":
        return _books_add_command(args[1:])

    if sub == "ingest":
        print("Ingesting the book corpus into the FTS5/BM25 index…")
        stats = retriever.build_index()
        if stats.discovered:
            print(f"  auto-discovered {len(stats.discovered)} new drop-in book(s): "
                  + ", ".join(stats.discovered))
        print(f"\nIndexed {stats.books_indexed} books, {stats.total_chunks} chunks.")
        for slug, n in stats.per_book.items():
            print(f"  {slug:28s} {n:>5d} chunks")
        for title, reason in stats.excluded:
            print(f"\n  WARNING — EXCLUDED (never indexed): {title}\n    reason: {reason}")
        print(f"\nIndex: {stats.index_path}")
        return 0

    if sub == "status":
        st = retriever.index_status()
        core = manifest.core_books()
        user = manifest.user_books()
        print("Corpus manifest:")
        for spec in core:
            if spec.included:
                print(f"  [included] {spec.slug:28s} {spec.title}")
        for spec in user:
            if spec.included:
                src = f"  (from {spec.source})" if spec.source else ""
                print(f"  [user]     {spec.slug:28s} {spec.title}{src}")
        for spec in manifest.excluded_books():
            print(f"  [EXCLUDED] {spec.slug:28s} {spec.title}")
            print(f"             reason: {spec.exclusion_reason}")
        print()
        print(f"Corpus dir: {manifest.corpus_dir()}")
        print(f"  core books: {sum(1 for s in core if s.included)}  |  "
              f"user-added: {sum(1 for s in user if s.included)}  |  "
              f"excluded: {len(manifest.excluded_books())}")
        if st.exists:
            print(f"Index: {st.path}  ({st.total_chunks} chunks across {len(st.per_book)} books)")
        else:
            print(f"Index: {st.path}  — NOT BUILT. Run: dr-alex books ingest")
        print("\nAdd a book:  dr-alex books add <file.pdf|file.txt> [--title \"…\"] [--authors \"…\"]")
        print("…or just drop a .txt/.pdf into the corpus dir and run: dr-alex books ingest")
        return 0

    print(f"Unknown books subcommand: {sub!r}. Use 'ingest', 'status', or 'add'.",
          file=sys.stderr)
    return 2


def _books_add_command(args: list[str]) -> int:
    """`dr-alex books add <path> [--title "…"] [--authors "…"]` — register + index a book."""
    from books import dropin, extract, retriever

    positionals = [a for i, a in enumerate(args)
                   if not a.startswith("--")
                   and not (i > 0 and args[i - 1] in ("--title", "--authors"))]
    if not positionals:
        print("Usage: dr-alex books add <file.pdf|file.txt> [--title \"…\"] [--authors \"…\"]",
              file=sys.stderr)
        return 2
    path = positionals[0]
    title = _opt(args, "--title")
    authors = _opt(args, "--authors")

    try:
        res = dropin.add_book(path, title=title, authors=authors)
    except FileNotFoundError as exc:
        print(f"books add: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"books add: {exc}", file=sys.stderr)
        return 2
    except extract.PdfLibraryMissing as exc:
        # Graceful: a PDF was dropped without the (optional) PDF lib. One-line hint, no crash.
        print(f"books add: {exc}", file=sys.stderr)
        return 1

    if not res.included:
        print(f"Registered but EXCLUDED (never indexed): {res.title}")
        print(f"  reason: {res.exclusion_reason}")
        print("  Fix the source (better extraction / a real text file) and re-add.")
        return 1

    print(f"Added: {res.title}")
    print(f"  slug:     {res.slug}")
    print(f"  filename: {res.filename}  ({res.chars} chars of text)")
    print("Rebuilding the index…")
    stats = retriever.build_index()
    n = stats.per_book.get(res.slug, 0)
    print(f"  indexed {n} chunks (corpus now {stats.books_indexed} books, "
          f"{stats.total_chunks} chunks total).")
    print(f"Index: {stats.index_path}")
    return 0


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


def _opt(args: list[str], name: str) -> str | None:
    """Read ``--name value`` or ``--name=value`` from args; None if absent."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _checkin_command(args: list[str]) -> int:
    """`dr-alex checkin [--notify]` — the TUI opener, or the launchd notification path."""
    if "--notify" in args:
        from dr_alex import checkin

        posted = checkin.run_checkin_notify()
        # Body-free status only (R3): never echo any therapy data (there is none on this path).
        print("check-in notification posted." if posted
              else "check-in notification could not be posted (non-fatal).", file=sys.stderr)
        return 0
    if "--install-plist" in args:
        from dr_alex import checkin

        print("Nightly check-in LaunchAgent (DISABLED by default). To enable (one command):")
        print(f"  cp {checkin.plist_relpath()} ~/Library/LaunchAgents/ \\")
        print(f"    && launchctl load -w ~/Library/LaunchAgents/{checkin.PLIST_LABEL}.plist")
        print(f"  (default {21:02d}:{30:02d}; body is a FIXED string, never any therapy data)")
        return 0
    from dr_alex import app

    app.run("checkin")
    return 0


def _export_command(args: list[str]) -> int:
    """`dr-alex export --from <date> --to <date> [--redaction summary|full]`."""
    from dr_alex import export

    frm = _opt(args, "--from")
    to = _opt(args, "--to")
    redaction = _opt(args, "--redaction") or "summary"
    if not frm or not to:
        print("Usage: dr-alex export --from YYYY-MM-DD --to YYYY-MM-DD "
              "[--redaction summary|full]", file=sys.stderr)
        return 2
    res = export.export_range(frm, to, redaction=redaction, write=True)
    if not res.ok:
        print(f"export failed: {res.error}", file=sys.stderr)
        return 1
    print(f"Export ({res.redaction}) {res.from_date} → {res.to_date}:")
    print(f"  markdown: {res.markdown_path}")
    print(f"  html:     {res.html_path}")
    print("  Open the HTML and use the browser's print-to-PDF. Nothing was sent.")
    return 0


def _review_command(args: list[str]) -> int:
    """`dr-alex review [--days N] [--redaction summary|full]` — default last-30-days export."""
    from dr_alex import export

    redaction = _opt(args, "--redaction") or "summary"
    days = 30
    d = _opt(args, "--days")
    if d:
        try:
            days = int(d)
        except ValueError:
            print(f"bad --days value: {d}", file=sys.stderr)
            return 2
    res = export.review(days=days, redaction=redaction, write=True)
    if not res.ok:
        print(f"review failed: {res.error}", file=sys.stderr)
        return 1
    print(f"Review export ({res.redaction}) last {days} days → {res.html_path}")
    print("  Open the HTML and print-to-PDF. Nothing was sent.")
    return 0


def _shreya_command(args: list[str]) -> int:
    """`dr-alex shreya [--days N] [--print]` — generate the G11 Friday Shreya-prep packet."""
    from dr_alex import shreya_packet

    days = 7
    do_print = False
    for a in args:
        if a.startswith("--days="):
            try:
                days = int(a.split("=", 1)[1])
            except ValueError:
                print(f"bad --days value: {a}", file=sys.stderr)
                return 2
        elif a == "--print":
            do_print = True
    res = shreya_packet.generate(window_days=days)
    if res.out_path:
        print(f"Shreya-prep packet: {res.out_path}"
              + ("" if res.ok else "  (GENERATION FAILED — see the loud placeholder inside)"))
    if do_print:
        print("\n" + res.text)
    return 0 if res.ok else 1


def _records_command(args: list[str]) -> int:
    """`dr-alex records` — print the canonical Active File path (scaffolding it if absent)."""
    from dr_alex import records

    p = records.ensure_scaffold()
    print(f"Canonical Active File: {p}")
    return 0


def _notion_command(args: list[str]) -> int:
    """`dr-alex notion status` — report mirror enablement WITHOUT ever printing a secret."""
    from dr_alex import notion

    sub = args[0] if args else "status"
    if sub != "status":
        print(f"Unknown notion subcommand: {sub!r}. Use 'status'.", file=sys.stderr)
        return 2
    cfg = notion.load_notion_config()
    if cfg is None:
        print("Notion mirror: DISABLED (no token in the macOS Keychain).")
        print("To enable, run these in a terminal (Prax only — the model never sees the values):")
        print(f"  security add-generic-password -s {notion.crypto.SERVICE} "
              f"-a {notion.TOKEN_ACCOUNT}       -w '<notion_integration_token>'")
        print(f"  security add-generic-password -s {notion.crypto.SERVICE} "
              f"-a {notion.SESSIONS_DB_ACCOUNT} -w '<sessions_database_id>'")
        print(f"  security add-generic-password -s {notion.crypto.SERVICE} "
              f"-a {notion.HOMEWORK_DB_ACCOUNT} -w '<homework_database_id>'")
        return 0
    print("Notion mirror: ENABLED (token present in Keychain).")
    print(f"  sessions DB configured: {'yes' if cfg.sessions_db else 'NO — set it'}")
    print(f"  homework DB configured: {'yes' if cfg.homework_db else 'NO — set it'}")
    print(f"  detail level: {notion.config.notion_detail_level()}  "
          "(RED sessions are always forced to summary + 'reviewed offline')")
    return 0


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

    if args and args[0] == "improve":
        return _improve_command(args[1:])

    if args and args[0] == "export":
        return _export_command(args[1:])

    if args and args[0] == "review":
        return _review_command(args[1:])

    if args and args[0] == "shreya":
        return _shreya_command(args[1:])

    if args and args[0] == "records":
        return _records_command(args[1:])

    if args and args[0] == "notion":
        return _notion_command(args[1:])

    if not args:
        from dr_alex import app

        app.run("full")
        return 0

    if args[0] == "checkin":
        return _checkin_command(args[1:])

    # Anything else: treat the joined arguments as a one-shot message.
    return _print_oneshot(" ".join(args))


if __name__ == "__main__":
    raise SystemExit(main())
