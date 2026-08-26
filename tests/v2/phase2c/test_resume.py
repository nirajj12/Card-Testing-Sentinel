from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from card_testing_sentinel.v2.phase2c.amendment import (
    LEDGER_COMPLETION_PATH,
    refuse_if_already_resumed,
)
from card_testing_sentinel.v2.phase2c.resumed_evaluation import (
    _verify_final_manifest,
    _write_completion,
)


def test_append_only_completion_and_second_run_refusal(tmp_path: Path):
    completion = tmp_path / LEDGER_COMPLETION_PATH
    completion.parent.mkdir(parents=True)
    digest = _write_completion(completion, {"scoring_attempt": 1})
    assert digest == hashlib.sha256(completion.read_bytes()).hexdigest()
    assert completion.with_suffix(".sha256").read_text().strip() == digest
    with pytest.raises(PermissionError, match="second"):
        _write_completion(completion, {"scoring_attempt": 1})
    with pytest.raises(PermissionError, match="second"):
        refuse_if_already_resumed(tmp_path)


def test_final_manifest_verifies_every_protected_hash(tmp_path: Path):
    output = tmp_path / "artifacts/v2/phase2c/confirmation"
    output.mkdir(parents=True)
    protected = tmp_path / "protected.json"
    protected.write_text("fixture")
    manifest = {
        "protected_hashes": {
            "protected.json": hashlib.sha256(protected.read_bytes()).hexdigest()
        }
    }
    path = output / "final_hash_manifest.json"
    path.write_text(json.dumps(manifest))
    path.with_suffix(".sha256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert _verify_final_manifest(tmp_path) == manifest
    protected.write_text("drift")
    with pytest.raises(PermissionError, match="result drift"):
        _verify_final_manifest(tmp_path)
