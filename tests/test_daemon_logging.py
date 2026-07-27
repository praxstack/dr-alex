"""The audit/trace loggers must actually be DELIVERED, not just formatted correctly.

``test_wire_audit`` and ``test_trace_logging`` use ``caplog.at_level(...)``, which forces both
the level and a handler — so they asserted log CONTENT while production silently dropped every
INFO line (``dr_alex.*`` inherited root's WARNING level with no handler anywhere, and uvicorn
configures only its own loggers). These tests assert DELIVERY instead.
"""

from __future__ import annotations

import logging
import time

import pytest

from dr_alex import alexd


@pytest.fixture()
def _isolated_dr_alex_logger():
    lg = logging.getLogger("dr_alex")
    saved_handlers, saved_level = list(lg.handlers), lg.level
    for h in list(lg.handlers):
        lg.removeHandler(h)
    yield lg
    for h in list(lg.handlers):
        lg.removeHandler(h)
    for h in saved_handlers:
        lg.addHandler(h)
    lg.setLevel(saved_level)


def test_audit_and_trace_lines_are_actually_enabled(monkeypatch, tmp_path,
                                                    _isolated_dr_alex_logger) -> None:
    monkeypatch.setattr(alexd, "log_dir", lambda: tmp_path / "logs")
    assert logging.getLogger("dr_alex.wire").isEnabledFor(logging.INFO) is False

    alexd._configure_daemon_logging()

    # This is the assertion whose absence let the defect ship.
    assert logging.getLogger("dr_alex.wire").isEnabledFor(logging.INFO) is True
    assert logging.getLogger("dr_alex.trace").isEnabledFor(logging.INFO) is True
    assert logging.getLogger("dr_alex.alexd").isEnabledFor(logging.WARNING) is True


def test_logging_config_is_idempotent(monkeypatch, tmp_path, _isolated_dr_alex_logger) -> None:
    monkeypatch.setattr(alexd, "log_dir", lambda: tmp_path / "logs")
    alexd._configure_daemon_logging()
    n = len(_isolated_dr_alex_logger.handlers)
    alexd._configure_daemon_logging()
    assert len(_isolated_dr_alex_logger.handlers) == n, "handlers must not accumulate"


def test_log_file_is_written_bounded_and_0600(monkeypatch, tmp_path,
                                              _isolated_dr_alex_logger) -> None:
    import os
    import stat

    d = tmp_path / "logs"
    monkeypatch.setattr(alexd, "log_dir", lambda: d)
    alexd._configure_daemon_logging()

    from dr_alex import wire
    from safety.triage import Tier

    wire.audit_turn(tier=Tier.GREEN, safety_path_taken="none", chunk_ids=["b:1"])
    for h in _isolated_dr_alex_logger.handlers:
        h.flush()

    target = d / "alexd.log"
    assert target.is_file()
    assert "tier=GREEN" in target.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    # Bounded: a rotating handler with a hard ceiling, never an unbounded file.
    from logging.handlers import RotatingFileHandler
    rotators = [h for h in _isolated_dr_alex_logger.handlers
                if isinstance(h, RotatingFileHandler)]
    assert rotators and rotators[0].maxBytes > 0 and rotators[0].backupCount > 0


def test_unusable_log_dir_degrades_to_stderr_and_never_raises(monkeypatch, tmp_path,
                                                              _isolated_dr_alex_logger) -> None:
    # A file that cannot be opened must NOT take the daemon down — this app crash-looped 1,810
    # times over exactly this class of fault.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(alexd, "log_dir", lambda: blocker / "logs")

    alexd._configure_daemon_logging()  # must not raise

    assert _isolated_dr_alex_logger.handlers, "stderr logging must survive a bad log path"
    assert logging.getLogger("dr_alex.wire").isEnabledFor(logging.INFO) is True


def test_launchd_log_trim_preserves_evidence_and_bounds_size(monkeypatch, tmp_path) -> None:
    d = tmp_path / "logs"
    d.mkdir()
    monkeypatch.setattr(alexd, "log_dir", lambda: d)
    monkeypatch.setattr(alexd, "_LAUNCHD_LOG_MAX_BYTES", 100)

    big = d / "dr-alex-alexd.err.log"
    big.write_text("x" * 500, encoding="utf-8")
    small = d / "dr-alex-alexd.out.log"
    small.write_text("keep me", encoding="utf-8")

    alexd._trim_launchd_logs()

    assert big.stat().st_size == 0, "over-cap file is truncated in place (launchd holds the fd)"
    assert (d / "dr-alex-alexd.err.log.1").read_text(encoding="utf-8") == "x" * 500, \
        "the previous content is preserved — the point is to KEEP evidence, not destroy it"
    assert small.read_text(encoding="utf-8") == "keep me", "under-cap files are untouched"


def test_trim_is_a_noop_when_the_dir_does_not_exist(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(alexd, "log_dir", lambda: tmp_path / "nope")
    alexd._trim_launchd_logs()  # must not raise


def test_daemon_logs_are_not_in_tmp() -> None:
    # /tmp is wiped at every boot on this machine, which permanently destroyed the postmortem
    # for the 1,810-restart crash loop.
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    plist = (root / "tools" / "launchd" / "com.prax.dralex-alexd.plist").read_text(encoding="utf-8")
    assert "/tmp/" not in plist
    assert "<string>/Users/prax/dr-alex/logs/dr-alex-alexd.err.log</string>" in plist
    assert "<string>/Users/prax/dr-alex/logs/dr-alex-alexd.out.log</string>" in plist
    # The dir must be tracked (empty) — launchd does not create intermediate directories and
    # silently discards output when it cannot open the path.
    assert (root / "logs" / ".gitkeep").exists()


def test_periodic_launchd_log_trimmer_fires_while_serving(tmp_path):
    """The trimmer must run for the LIFE of the process, not once at startup.

    Startup-only trimming bounds nothing on a daemon meant to stay up for weeks — which is
    exactly this one. Drives a real app through its lifespan with a compressed interval.
    """
    from unittest import mock

    from fastapi.testclient import TestClient

    from dr_alex import alexd

    big = tmp_path / "dr-alex-alexd.err.log"
    big.write_bytes(b"x" * 500)

    with (
        mock.patch.object(alexd, "log_dir", lambda: tmp_path),
        mock.patch.object(alexd, "_LAUNCHD_LOG_MAX_BYTES", 100),
        mock.patch.object(alexd, "_LAUNCHD_LOG_TRIM_INTERVAL_S", 0.05),
        TestClient(alexd.create_app()) as client,
    ):
        client.get("/healthz")
        deadline = time.time() + 5
        while time.time() < deadline and big.stat().st_size > 100:
            time.sleep(0.05)

    assert big.stat().st_size == 0, "periodic trim never fired"
    assert (tmp_path / "dr-alex-alexd.err.log.1").exists(), "previous content not preserved"


def test_lifespan_shutdown_does_not_hang(tmp_path):
    """Exiting the app must cancel the trimmer promptly — a shutdown that hangs is an outage."""
    from fastapi.testclient import TestClient

    from dr_alex import alexd

    started = time.time()
    with TestClient(alexd.create_app()) as client:
        client.get("/healthz")
    assert time.time() - started < 10, "lifespan shutdown hung on the background task"
