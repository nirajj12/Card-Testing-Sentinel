"""Run the official one-time Blind v2 evaluation or its no-score preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from card_testing_sentinel.ml.blind_v2_evaluation import (
    causal_frame,
    run_official_evaluation,
    verify_pre_evaluation,
)

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = Path(__file__).resolve()
EVALUATOR = ROOT / "src/card_testing_sentinel/ml/blind_v2_evaluation.py"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="verify hashes and causal replay without loading or scoring Model v2",
    )
    args = parser.parse_args()
    if args.preflight:
        checks = verify_pre_evaluation(ROOT)
        _, replay = causal_frame(ROOT)
        print(json.dumps({**checks, "causal_replay": replay}, indent=2, sort_keys=True))
    else:
        result = run_official_evaluation(ROOT, EVALUATOR, PIPELINE)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "evaluated": result["evaluated"],
                    "consumed": result["consumed"],
                    "first_successful_score_utc": result["consumption"][
                        "first_successful_score_utc"
                    ],
                    "verdict": result["verdict"],
                },
                indent=2,
                sort_keys=True,
            )
        )
