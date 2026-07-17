"""`dr-alex` console entry point.

Modes
-----
    dr-alex               full warm session (Textual TUI)
    dr-alex checkin       gentle nightly "how was today?" opener (TUI)
    dr-alex "some text"   one-shot: a single safety-first exchange, printed and done
    dr-alex --card        print the crisis card (pure, no LLM) and exit
    dr-alex --version
"""

from __future__ import annotations

import sys

from dr_alex import __version__


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
