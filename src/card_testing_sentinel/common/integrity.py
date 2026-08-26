"""Release-integrity helpers shared by runtime and verification tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def verify_manifest(root: Path, manifest_path: Path) -> dict:
    manifest = load_json(manifest_path)
    for name, entry in manifest["artifacts"].items():
        path = root / entry["path"]
        if not path.is_file():
            raise FileNotFoundError(f"required release artifact is missing: {name}")
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise ValueError(f"release artifact hash mismatch: {name}")
    return manifest
