from __future__ import annotations

import shutil
from pathlib import Path


PROJECT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def copy_test_workspace(root: Path) -> None:
    """Build a disposable app tree without copying production/user material."""
    for name in ("templates", "static"):
        shutil.copytree(PROJECT / name, root / name)
    shutil.copytree(FIXTURES / "data", root / "data")
    (root / "sources").mkdir()
