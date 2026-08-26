"""Generate the one authorized Phase 2B fresh-validation dataset."""

import argparse
import json
from pathlib import Path

from card_testing_sentinel.v2.phase2b.fresh_validation import (
    FRESH_SEED,
    sha256_file,
    write_fresh_validation_bundle,
)

ROOT = Path(__file__).resolve().parents[3]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--verify-freeze", required=True, type=Path)
    result.add_argument("--seed", required=True, type=int)
    result.add_argument("--output", required=True, type=Path)
    return result


def main() -> int:
    arguments = parser().parse_args()
    freeze = (ROOT / arguments.verify_freeze).resolve()
    expected = ROOT / "artifacts/v2/phase2b/training/freeze/training_freeze.json"
    if (
        freeze != expected.resolve()
        or sha256_file(freeze)
        != (ROOT / "artifacts/v2/phase2b/training/freeze/training_freeze.sha256")
        .read_text()
        .strip()
    ):
        raise PermissionError("the authoritative Phase 2B training freeze is required")
    if arguments.seed != FRESH_SEED:
        raise PermissionError(f"fresh-validation seed must be {FRESH_SEED}")
    output = (ROOT / arguments.output).resolve()
    manifest = write_fresh_validation_bundle(
        root=ROOT,
        config_path=ROOT / "configs/v2/phase2b/fresh_validation.yaml",
        output_dir=output,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
