"""Benchmark and freeze Phase 2B validation semantics before real access."""

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json
from card_testing_sentinel.v2.phase2b.fresh_validation import (
    FRESH_SEED,
    generate_fresh_frames,
    sha256_file,
    write_execution_freeze,
)
from card_testing_sentinel.v2.phase2b.validation_policy import (
    OptimizedFrozenScorer,
    allow_all_replay,
    benchmark_candidates,
)

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "artifacts/v2/phase2b/validation"

PROTECTED = (
    "artifacts/v2/phase2b/training/freeze/training_freeze.json",
    "artifacts/v2/phase2b/training/models/selected_model.joblib",
    "artifacts/v2/phase2b/training/models/model_feature_contract.json",
    "artifacts/v2/phase2b/training/models/model_metadata.json",
    "artifacts/v2/phase2b/training/policy/policy_search_space.json",
    "configs/v2/phase2b/fresh_validation.yaml",
    "configs/v2/phase2b/features.yaml",
    "configs/v2/phase2b/policy_grid_proposal.yaml",
    "configs/v2/phase2b/requirements-lock.txt",
    "configs/v2/policy.yaml",
    "src/card_testing_sentinel/v2/data/generator.py",
    "src/card_testing_sentinel/v2/data/contracts.py",
    "src/card_testing_sentinel/v2/phase2b/engine.py",
    "src/card_testing_sentinel/v2/phase2b/batch.py",
    "src/card_testing_sentinel/v2/phase2b/features.py",
    "src/card_testing_sentinel/v2/phase2b/fresh_validation.py",
    "src/card_testing_sentinel/v2/phase2b/validation_policy.py",
    "src/card_testing_sentinel/v2/policy/rules.py",
    "src/card_testing_sentinel/v2/policy/selection.py",
    "src/card_testing_sentinel/v2/evaluation/metrics.py",
    "src/card_testing_sentinel/v2/modeling/weights.py",
    "scripts/v2/phase2b/freeze_validation_methodology.py",
    "scripts/v2/phase2b/generate_fresh_validation.py",
    "scripts/v2/phase2b/evaluate_fresh_validation.py",
    "tests/v2/phase2b/test_fresh_validation.py",
    "tests/v2/phase2b/test_validation_policy.py",
)


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError("validation artifact directory already exists")
    config = yaml.safe_load(
        (ROOT / "configs/v2/phase2b/fresh_validation.yaml").read_text()
    )
    tiny = dict(config)
    tiny["device_counts"] = {name: 2 for name in config["device_counts"]}
    raw, contract = generate_fresh_frames(tiny)
    artifact = joblib.load(
        ROOT / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    scorer = OptimizedFrozenScorer(artifact)
    features = allow_all_replay(raw)
    parity = scorer.verify_parity(features)
    policy = json.loads(
        (
            ROOT / "artifacts/v2/phase2b/training/policy/policy_search_space.json"
        ).read_text()
    )
    feature_contract = json.loads(
        (
            ROOT / "artifacts/v2/phase2b/training/models/model_feature_contract.json"
        ).read_text()
    )
    benchmark = benchmark_candidates(raw, contract, scorer, policy["candidates"])
    benchmark["optimized_score_parity"] = parity
    OUTPUT.mkdir(parents=True)
    atomic_write_json(OUTPUT / "pre_access_runtime_benchmark.json", benchmark)
    payload = {
        "version": "v2-phase2b-validation-execution-freeze-1",
        "created_utc": datetime.now(UTC).isoformat(),
        "fresh_validation_seed": FRESH_SEED,
        "expected_scenario_denominators": config["device_counts"],
        "candidate_count": policy["candidate_count"],
        "candidate_family_counts": policy["family_counts"],
        "training_freeze_sha256": sha256_file(
            ROOT / "artifacts/v2/phase2b/training/freeze/training_freeze.json"
        ),
        "frozen_model_and_calibrator_sha256": sha256_file(
            ROOT / "artifacts/v2/phase2b/training/models/selected_model.joblib"
        ),
        "feature_order_sha256": feature_contract["feature_contract_sha256"],
        "budgets": policy["budgets"],
        "selection_objective": policy["selection_objective"],
        "tie_break": (
            "comparison_tuple: worst subtype review, macro subtype review, worst "
            "subtype block, macro subtype block, lower delay, fewer legitimate "
            "blocks, fewer legitimate reviews, simpler family, conservative "
            "thresholds, canonical candidate JSON"
        ),
        "causal_replay_semantics": (
            "score immediately before outcome; allow/review commit outcomes; block "
            "suppresses current outcome and tied completion plus later device state"
        ),
        "output_paths": {
            "data": "data/v2/phase2b/fresh_validation",
            "artifacts": "artifacts/v2/phase2b/validation",
            "reports": "reports/v2/phase2b/validation",
        },
        "access_time_policy": "one atomic ledger at first scoring access; no rerun",
        "refusal_conditions": [
            "wrong seed",
            "existing output",
            "training or execution freeze drift",
            "dataset manifest drift",
            "second generation or scoring attempt",
            "identifier overlap",
            "structural denominator drift",
            "parity failure",
            "candidate count other than 78",
        ],
        "mlflow_packaging_mismatch": (
            "runtime uses mlflow-skinny==3.15.1 while project metadata names mlflow; "
            "imports and temporary local FileStore passed; no package was changed"
        ),
        "pre_access_benchmark_sha256": sha256_file(
            OUTPUT / "pre_access_runtime_benchmark.json"
        ),
    }
    path, digest = write_execution_freeze(
        root=ROOT,
        freeze_path=OUTPUT / "execution_freeze.json",
        protected_paths=PROTECTED,
        payload=payload,
    )
    print(
        json.dumps(
            {"freeze": str(path), "sha256": digest, "benchmark": benchmark}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
