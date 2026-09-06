"""Check built release archives: python tools/check-package.py <wheel> <sdist>."""

import sys
import tarfile
import zipfile
from pathlib import PurePosixPath


for artifact in sys.argv[1:]:
    if artifact.endswith(".whl"):
        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
        assert len(names) == len(set(names)), "duplicate wheel entries"
        for required in (
            "room/app.js", "room/app.css", "room/index.html",
            "therapy_api.py", "subscription_backend.py", "history_recall.py",
        ):
            assert "dr_alex/" + required in names, required
        data_prefix = "dr_alex/_bundled/data/"
    else:
        with tarfile.open(artifact) as archive:
            names = [name.split("/", 1)[-1] for name in archive.getnames()]
        data_prefix = "data/"
    assert {name for name in names if name.startswith(data_prefix)} == {
        data_prefix + "crisis-card.md", data_prefix + "crisis-card.txt",
    }, "unexpected data payload"
    for name in names:
        parts = PurePosixPath(name).parts
        assert not {"records", "backups", "transcripts", "inbox"}.intersection(parts), name
        assert not name.endswith((".db", ".enc", ".bundle", "-wal", "-shm")), name
assert len(sys.argv) > 1, "supply built wheel/sdist paths"
print("PASS: assets present once; private runtime data absent")
