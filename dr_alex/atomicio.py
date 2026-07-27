"""One atomic file write, used by every durable writer in the app.

Four modules had grown their own temp+replace idiom and they had silently diverged: one
fsynced the file and the directory, two fsynced only the file, one fsynced nothing — while
a docstring in a fourth claimed they were all "the same idiom". That divergence is invisible
in review and only shows up as a lost file after a power cut, so the fix is to have exactly
one implementation rather than a convention everyone is asked to remember.

Durability, precisely:
  * ``fsync`` on the temp file BEFORE the rename — a failure leaves the previous good file
    completely intact, because the rename never happens.
  * ``fsync`` on the parent directory AFTER the rename — this is what makes the *rename*
    itself durable. Without it the data survives but the file can come back under the old
    name (or missing) after a crash.
  * Both fsyncs are best-effort: on a filesystem that refuses them, a raised error here would
    be a brand-new failure mode in call paths that have no local handling, which is worse
    than the narrower durability window. (On Darwin ``os.fsync`` does not flush the drive's
    write cache — that needs ``F_FULLFSYNC`` — so this narrows the power-loss window rather
    than closing it.)

``OSError`` still propagates for real write failures, matching what ``Path.write_text`` did.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(
    path: Path,
    text: str,
    *,
    mode: int = 0o600,
    dir_mode: int | None = 0o700,
    prefix: str | None = None,
) -> None:
    """Write ``text`` to ``path`` atomically: temp + fsync + ``os.replace`` + dir fsync.

    ``prefix`` names the temp file so a stray one is attributable to its writer; it must stay
    dot-prefixed, because the hygiene guard and .gitignore both match on that.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if dir_mode is not None:
        try:
            os.chmod(path.parent, dir_mode)
        except OSError:
            pass  # SILENT-BY-DESIGN: perms are hardened elsewhere; never block the write

    tmp_prefix = prefix or f".{path.name}."
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=tmp_prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass  # SILENT-BY-DESIGN: best-effort durability, never a new raise point
        os.chmod(tmp, mode)  # before the replace: never briefly visible at umask perms
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        try:
            os.unlink(tmp)  # no-op on success: the name is gone after the replace
        except OSError:
            pass  # SILENT-BY-DESIGN: cleanup of an already-renamed temp


def _fsync_dir(directory: Path) -> None:
    """Make the rename durable. Best-effort; see the module docstring."""
    try:
        dfd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass  # SILENT-BY-DESIGN: best-effort durability, never a new raise point
