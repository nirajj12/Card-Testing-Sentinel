"""Run the single authorized PBRSS-v1 score, or a no-score preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from card_testing_sentinel.ml.pbrss_v1_evaluation import (
    run_one_score,
    verify_pre_evaluation,
)

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    result = verify_pre_evaluation(ROOT) if args.preflight else run_one_score(ROOT)
    print(json.dumps(result, indent=2, sort_keys=True))
