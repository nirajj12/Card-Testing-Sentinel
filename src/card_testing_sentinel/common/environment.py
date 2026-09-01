"""Small server-side .env loader for local development.

Only explicitly requested keys are loaded, existing process environment wins,
and values are never logged or returned to callers.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_local_environment(root: Path, keys: tuple[str, ...]) -> None:
    path = root / ".env"
    if not path.is_file():
        return
    allowed = set(keys)
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value
