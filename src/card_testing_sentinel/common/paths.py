"""Locate external immutable artifacts/configuration in source and wheel installs."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the repository/image root containing configs and artifacts.

    The runtime artifacts intentionally remain external to the Python wheel. A source
    install can resolve them relative to this module; a non-editable wheel (including
    Docker) resolves them from its working directory or an explicit deployment root.
    """
    candidates = []
    configured = os.environ.get("CTS_PROJECT_ROOT")
    if configured:
        candidates.append(Path(configured).expanduser().resolve())
    candidates.extend((Path.cwd().resolve(), Path(__file__).resolve().parents[3]))
    for candidate in candidates:
        if (
            (candidate / "configs/app.yaml").is_file()
            and (candidate / "configs/features.yaml").is_file()
            and (candidate / "artifacts/release_manifest.json").is_file()
        ):
            return candidate
    raise FileNotFoundError(
        "Card-Testing Sentinel project root was not found; run from the project "
        "directory or set CTS_PROJECT_ROOT"
    )
