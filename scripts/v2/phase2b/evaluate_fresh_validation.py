"""Run the single authorized Phase 2B validation and frozen policy evaluation."""

import json
from pathlib import Path

from card_testing_sentinel.v2.phase2b.validation_policy import run_fresh_validation

ROOT = Path(__file__).resolve().parents[3]

if __name__ == "__main__":
    print(json.dumps(run_fresh_validation(ROOT), indent=2, sort_keys=True))
