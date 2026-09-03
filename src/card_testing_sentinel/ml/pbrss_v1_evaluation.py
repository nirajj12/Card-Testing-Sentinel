"""Freeze and one-score governance for PBRSS-v1.

The canonical scored path has no fitting or selection operation.  It verifies
the frozen bundle, loads the already-frozen Model v3.1, scores once, atomically
records consumption, and only then computes or writes evaluation results.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from card_testing_sentinel.features.specification_v3 import (
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
)
from card_testing_sentinel.ml.metrics import (
    device_weights,
    probability_metrics,
    reliability_bins,
)
from card_testing_sentinel.policy.engine_v2 import RiskPolicyV2

SUITE_ID = "pbrss-v1"
PRE_PBRSS_COMMIT = "1c9dab4ed2902b4207e6758f1c929fee1b8a08dc"
DATA_FILES = ("raw_events.csv", "labels.csv", "features_v3_1.csv", "manifest.json")
POLICY_FIELDS = (
    "family",
    "review_threshold",
    "block_threshold",
    "block_evidence",
    "evidence_set",
    "trust_suppression",
    "block_ttl_seconds",
    "campaign_review_increment",
    "campaign_block_increment",
    "degraded_review_rule_score",
    "degraded_block_rule_score",
)


class PBRSSV1EvaluationError(RuntimeError):
    """A freeze or one-score precondition failed."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def build_freeze_manifest(root: Path, destination: Path | None = None) -> dict:
    """Build the deterministic manifest after canonical generation.

    No clock value is included: identical inputs produce identical bytes.
    """
    data_dir = root / "data/generated/post_blind_stress_v1"
    paths = {f"dataset/{name}": data_dir / name for name in DATA_FILES}
    paths.update(
        {
            "source/config": root / "configs/post_blind_stress_v1.yaml",
            "source/generator": root
            / "src/card_testing_sentinel/ml/pbrss_v1_generator.py",
            "source/feature_engine": root
            / "src/card_testing_sentinel/features/engine_v3.py",
            "source/feature_replay": root
            / "src/card_testing_sentinel/features/batch_v3.py",
            "source/evaluator": root
            / "src/card_testing_sentinel/ml/pbrss_v1_evaluation.py",
            "source/generation_pipeline": root
            / "pipelines/generate_post_blind_stress_v1.py",
            "source/evaluation_pipeline": root / "pipelines/evaluate_pbrss_v1_once.py",
            "foundation/model": root / "artifacts/model_v3_1/risk_model_v3_1.joblib",
            "foundation/model_metadata": root / "artifacts/model_v3_1/metadata.json",
            "foundation/feature_contract": root
            / "artifacts/model_v3_1/feature_contract.json",
            "foundation/policy": root
            / "artifacts/policy_v2/operational_policy_v2.json",
        }
    )
    missing = [
        str(path.relative_to(root)) for path in paths.values() if not path.is_file()
    ]
    if missing:
        raise PBRSSV1EvaluationError(f"freeze inputs missing: {missing}")
    contract = json.loads(paths["foundation/feature_contract"].read_text())
    if tuple(contract.get("features", ())) != MODEL_FEATURES_V3:
        raise PBRSSV1EvaluationError(
            "artifact feature contract is not the exact v3.1 order"
        )
    data_manifest = json.loads(paths["dataset/manifest.json"].read_text())
    if data_manifest.get("evaluated") or data_manifest.get("consumed"):
        raise PBRSSV1EvaluationError("dataset manifest is not pristine")
    manifest = {
        "suite_id": SUITE_ID,
        "spec_version": "pbrss-v1-frozen-spec",
        "generator_version": "pbrss-v1-generator-1",
        "pre_pbrss_model_freeze_commit": PRE_PBRSS_COMMIT,
        "feature_contract_version": "merchant-visible-causal-3.1",
        "feature_contract_sha256": MODEL_FEATURES_V3_SHA256,
        "model_version": "model-v3.1",
        "calibration": "sigmoid",
        "policy_version": "validation-selected-v2",
        "files": {
            key: {
                "path": str(path.relative_to(root)),
                "sha256": sha256_file(path),
            }
            for key, path in sorted(paths.items())
        },
        "counts": {
            "events": data_manifest.get("events"),
            "authorization_requests": data_manifest.get("authorization_requests"),
            "devices": data_manifest.get("devices"),
            "attack_devices": data_manifest.get("attack_devices"),
            "legitimate_devices": data_manifest.get("legitimate_devices"),
            "merchants": data_manifest.get("merchants"),
            "scenarios": data_manifest.get("scenarios"),
        },
        "evaluated": False,
        "consumed": False,
        "one_score_only": True,
    }
    if destination is not None:
        write_json(destination, manifest)
    return manifest


def verify_pre_evaluation(root: Path) -> dict:
    freeze_path = root / "artifacts/evaluation/pbrss_v1_freeze_manifest.json"
    consumption = root / "artifacts/evaluation/pbrss_v1_consumption.json"
    if not freeze_path.is_file():
        raise PBRSSV1EvaluationError("PBRSS-v1 freeze manifest is missing")
    if consumption.exists():
        raise PBRSSV1EvaluationError("PBRSS-v1 has already been consumed")
    freeze = json.loads(freeze_path.read_text())
    required = {
        "suite_id": SUITE_ID,
        "pre_pbrss_model_freeze_commit": PRE_PBRSS_COMMIT,
        "feature_contract_sha256": MODEL_FEATURES_V3_SHA256,
        "model_version": "model-v3.1",
        "calibration": "sigmoid",
        "policy_version": "validation-selected-v2",
    }
    for key, expected in required.items():
        if freeze.get(key) != expected:
            raise PBRSSV1EvaluationError(f"freeze binding differs at {key}")
    if freeze.get("evaluated") or freeze.get("consumed"):
        raise PBRSSV1EvaluationError("PBRSS-v1 freeze is already consumed")
    verified = {}
    for key, record in freeze.get("files", {}).items():
        path = root / record["path"]
        if not path.is_file():
            raise PBRSSV1EvaluationError(f"frozen input missing: {record['path']}")
        actual = sha256_file(path)
        if actual != record["sha256"]:
            raise PBRSSV1EvaluationError(f"hash drift: {record['path']}")
        verified[key] = actual
    contract = json.loads(
        (root / "artifacts/model_v3_1/feature_contract.json").read_text()
    )
    if tuple(contract.get("features", ())) != MODEL_FEATURES_V3:
        raise PBRSSV1EvaluationError("frozen contract feature order changed")
    metadata = json.loads((root / "artifacts/model_v3_1/metadata.json").read_text())
    if metadata.get("model_version") != "model-v3.1":
        raise PBRSSV1EvaluationError("wrong frozen model version")
    metadata_contract = metadata.get("feature_contract", {})
    if metadata_contract.get("sha256") != MODEL_FEATURES_V3_SHA256:
        raise PBRSSV1EvaluationError("model metadata contract binding changed")
    if tuple(metadata_contract.get("features", ())) != MODEL_FEATURES_V3:
        raise PBRSSV1EvaluationError("model metadata feature order changed")
    if metadata.get("calibration", {}).get("method") != "sigmoid":
        raise PBRSSV1EvaluationError("Model v3.1 sigmoid calibration is not frozen")
    policy = json.loads(
        (root / "artifacts/policy_v2/operational_policy_v2.json").read_text()
    )
    if policy.get("version") != "validation-selected-v2":
        raise PBRSSV1EvaluationError("wrong frozen policy version")
    return {
        "status": "passed",
        "freeze_sha256": sha256_file(freeze_path),
        "verified_hashes": verified,
    }


def reserve_consumption(root: Path, preflight: dict, scoring_started: str) -> dict:
    """Atomically reserve the one permitted look after scoring succeeds."""
    freeze = json.loads(
        (root / "artifacts/evaluation/pbrss_v1_freeze_manifest.json").read_text()
    )
    record = {
        "suite": "post-blind-remediation-stress-v1",
        "scoring_started_utc": scoring_started,
        "consumed_at": datetime.now(UTC).isoformat(),
        "git_commit": git_head(root),
        "freeze_manifest_sha256": preflight["freeze_sha256"],
        "model": "model-v3.1",
        "feature_contract": "merchant-visible-causal-3.1",
        "calibration": "sigmoid",
        "policy": "validation-selected-v2",
        "pre_pbrss_model_freeze_commit": PRE_PBRSS_COMMIT,
        "stress_dataset_hashes": {
            key: value["sha256"]
            for key, value in freeze["files"].items()
            if key.startswith("dataset/")
        },
        "model_hash": freeze["files"]["foundation/model"]["sha256"],
        "feature_contract_hash": freeze["files"]["foundation/feature_contract"][
            "sha256"
        ],
        "policy_hash": freeze["files"]["foundation/policy"]["sha256"],
        "evaluation_runner_hash": freeze["files"]["source/evaluation_pipeline"][
            "sha256"
        ],
        "evaluated": True,
        "consumed": True,
        "status": "consumed",
        "post_stress_tuning": False,
    }
    path = root / "artifacts/evaluation/pbrss_v1_consumption.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as error:
        raise PBRSSV1EvaluationError("PBRSS-v1 has already been consumed") from error
    with os.fdopen(descriptor, "w") as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def _device_policy(
    frame: pd.DataFrame, scores: np.ndarray, policy: RiskPolicyV2
) -> pd.DataFrame:
    actions = []
    for snapshot, score, timestamp in zip(
        frame.loc[:, list(MODEL_FEATURES_V3)].to_dict("records"),
        scores,
        pd.to_datetime(frame.timestamp, format="ISO8601"),
        strict=True,
    ):
        actions.append(
            policy.decide(
                snapshot=snapshot,
                risk_score=float(score),
                timestamp=timestamp.to_pydatetime(),
                campaign_active=False,
            ).action
        )
    rows = frame[["device_id", "label", "scenario"]].copy()
    rows["action"] = actions
    rows["attempt"] = rows.groupby("device_id").cumcount() + 1
    return rows


def run_one_score(root: Path) -> dict:
    preflight = verify_pre_evaluation(root)
    frame = pd.read_csv(root / "data/generated/post_blind_stress_v1/features_v3_1.csv")
    ordered = tuple(column for column in frame.columns if column in MODEL_FEATURES_V3)
    if ordered != MODEL_FEATURES_V3:
        raise PBRSSV1EvaluationError(
            "stress feature order is not the exact 44-feature contract"
        )
    matrix = frame.loc[:, list(MODEL_FEATURES_V3)].to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        raise PBRSSV1EvaluationError("stress feature matrix contains non-finite values")
    artifact = joblib.load(root / "artifacts/model_v3_1/risk_model_v3_1.joblib")
    if tuple(getattr(artifact, "feature_names", ())) != MODEL_FEATURES_V3:
        raise PBRSSV1EvaluationError("loaded model feature order differs")
    if getattr(artifact, "feature_contract_sha256", None) != MODEL_FEATURES_V3_SHA256:
        raise PBRSSV1EvaluationError("loaded model contract binding differs")
    if getattr(artifact, "calibration_method", None) != "sigmoid":
        raise PBRSSV1EvaluationError("loaded model is not the frozen sigmoid artifact")
    started = datetime.now(UTC).isoformat()
    scores = artifact.score_frame(frame)
    consumption = reserve_consumption(root, preflight, started)

    weights = device_weights(frame)
    metrics = probability_metrics(frame.label.to_numpy(dtype=int), scores, weights)
    policy_data = json.loads(
        (root / "artifacts/policy_v2/operational_policy_v2.json").read_text()
    )
    policy = RiskPolicyV2({key: policy_data[key] for key in POLICY_FIELDS})
    attempts = _device_policy(frame, scores, policy)
    devices = attempts.groupby("device_id").agg(
        label=("label", "first"),
        scenario=("scenario", "first"),
        reviewed=(
            "action",
            lambda values: bool(values.isin(["review", "block"]).any()),
        ),
        blocked=("action", lambda values: bool(values.eq("block").any())),
    )
    metrics["policy"] = {
        "attack_review_or_higher_rate": float(
            devices.loc[devices.label.eq(1), "reviewed"].mean()
        ),
        "attack_block_rate": float(devices.loc[devices.label.eq(1), "blocked"].mean()),
        "legitimate_review_or_higher_rate": float(
            devices.loc[devices.label.eq(0), "reviewed"].mean()
        ),
        "legitimate_block_rate": float(
            devices.loc[devices.label.eq(0), "blocked"].mean()
        ),
    }
    metrics["policy"]["false_positives_per_10000_legitimate_devices"] = (
        metrics["policy"]["legitimate_review_or_higher_rate"] * 10_000
    )
    output = root / "artifacts/evaluation"
    write_json(output / "pbrss_v1_metrics.json", metrics)
    pd.DataFrame(reliability_bins(frame.label, scores, weights)).to_csv(
        output / "pbrss_v1_calibration.csv", index=False
    )
    devices.groupby(["scenario", "label"])[
        ["reviewed", "blocked"]
    ].mean().reset_index().to_csv(output / "pbrss_v1_family_metrics.csv", index=False)
    delay = {}
    for cut in (1, 2, 3, 5):
        subset = attempts.loc[attempts.attempt.le(cut)]
        detected = subset.groupby("device_id").action.apply(
            lambda values: bool(values.isin(["review", "block"]).any())
        )
        attack_ids = devices.index[devices.label.eq(1)]
        delay[str(cut)] = float(detected.reindex(attack_ids, fill_value=False).mean())
    first_detection = (
        attempts.loc[attempts.label.eq(1) & attempts.action.isin(["review", "block"])]
        .groupby("device_id")
        .attempt.min()
    )
    delay["median_first_detection_attempt"] = (
        float(first_detection.median()) if not first_detection.empty else None
    )
    delay["p90_first_detection_attempt"] = (
        float(first_detection.quantile(0.9)) if not first_detection.empty else None
    )
    write_json(output / "pbrss_v1_detection_delay.json", delay)
    pairs = frame.dropna(subset=["counterfactual_pair_id"])
    cpoa = {"pairs": 0, "ordering_accuracy": None}
    if not pairs.empty:
        work = (
            pairs.assign(score=scores)
            .groupby(["counterfactual_pair_id", "counterfactual_role"])
            .score.max()
            .unstack()
        )
        if {"attack", "legitimate_twin"}.issubset(work.columns):
            cpoa = {
                "pairs": int(len(work)),
                "ordering_accuracy": float((work.attack > work.legitimate_twin).mean()),
            }
    write_json(output / "pbrss_v1_counterfactual.json", cpoa)
    report = root / "reports/post_blind_stress_v1_evaluation_report.md"
    report.write_text(
        "# PBRSS-v1 One-Score Evaluation\n\n"
        "This report was produced by the consumed one-score evaluator. "
        "See `artifacts/evaluation/pbrss_v1_metrics.json` for aggregate "
        "device-weighted results and the adjacent frozen breakdown artifacts.\n"
    )
    return {"status": "complete", "consumption": consumption, "metrics": metrics}
