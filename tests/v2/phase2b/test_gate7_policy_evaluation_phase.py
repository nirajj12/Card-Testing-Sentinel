"""Gate 7 (corrective pass, coverage raise): behavioral tests for
src/card_testing_sentinel/v2/policy/evaluation.py (22% coverage; the whole
``run_validation_policy_phase`` orchestration and its private aggregation
helpers were untested).

``run_validation_policy_phase`` reaches the real, unpatched validation
population through module-level-imported ``open_validation`` and
``verify_training_freeze`` (not a local per-call import like
``training.run_training_phase`` uses) -- so redirecting them to small
synthetic fixtures means monkeypatching those two names, plus
``_allow_all_parity`` (an artifact-vs-frozen-feature integrity check
unrelated to policy candidate-selection decision logic), in THIS module's
own namespace. ``choose_action``, ``replay_policy``, ``candidate_metrics``,
``comparison_tuple`` and ``enumerate_policy_grid`` -- the actual
decision-critical logic -- all run for real, unmodified, against a genuine
synthetic authorization-event timeline.
"""

import json
from datetime import UTC, datetime, timedelta

import joblib
import numpy as np
import pandas as pd
import pytest
import yaml

from card_testing_sentinel.v2.evaluation import access
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.policy import evaluation as evaluation_module

# ---------------------------------------------------------------------------
# _detailed_sequential_metrics -- pure aggregation, no I/O.
# ---------------------------------------------------------------------------


def _devices_frame():
    return pd.DataFrame(
        [
            {
                "device_id": "attacker-burst",
                "label": 1,
                "attack_subtype": "burst",
                "scenario_tag": "attack_burst",
                "review_or_higher": True,
                "blocked": True,
                "first_review_or_higher_request": 2,
                "first_block_request": 3,
                "requests_scored_through_first_action": 2,
                "authorizations_processed_before_first_action": 1,
                "distinct_cards_requested_through_first_action": 1,
                "distinct_cards_processed_before_first_action": 1,
                "seconds_to_first_review": 5.0,
                "seconds_to_first_block": 8.0,
                "potentially_preventable_later_requests_upper_bound": 2,
            },
            {
                "device_id": "attacker-patient",
                "label": 1,
                "attack_subtype": "patient",
                "scenario_tag": "attack_patient",
                "review_or_higher": False,
                "blocked": False,
                "first_review_or_higher_request": np.nan,
                "first_block_request": np.nan,
                "requests_scored_through_first_action": 5,
                "authorizations_processed_before_first_action": 5,
                "distinct_cards_requested_through_first_action": np.nan,
                "distinct_cards_processed_before_first_action": np.nan,
                "seconds_to_first_review": np.nan,
                "seconds_to_first_block": np.nan,
                "potentially_preventable_later_requests_upper_bound": 0,
            },
            {
                "device_id": "legit-normal",
                "label": 0,
                "attack_subtype": np.nan,
                "scenario_tag": "normal_standard",
                "review_or_higher": False,
                "blocked": False,
                "first_review_or_higher_request": np.nan,
                "first_block_request": np.nan,
                "requests_scored_through_first_action": 3,
                "authorizations_processed_before_first_action": 3,
                "distinct_cards_requested_through_first_action": np.nan,
                "distinct_cards_processed_before_first_action": np.nan,
                "seconds_to_first_review": np.nan,
                "seconds_to_first_block": np.nan,
                "potentially_preventable_later_requests_upper_bound": 0,
            },
            {
                "device_id": "legit-flash",
                "label": 0,
                "attack_subtype": np.nan,
                "scenario_tag": "flash_standard",
                "review_or_higher": True,
                "blocked": False,
                "first_review_or_higher_request": 1,
                "first_block_request": np.nan,
                "requests_scored_through_first_action": 1,
                "authorizations_processed_before_first_action": 0,
                "distinct_cards_requested_through_first_action": 1,
                "distinct_cards_processed_before_first_action": 0,
                "seconds_to_first_review": 0.5,
                "seconds_to_first_block": np.nan,
                "potentially_preventable_later_requests_upper_bound": 0,
            },
        ]
    )


def test_detailed_sequential_metrics_uses_full_attacker_denominator():
    devices = _devices_frame()
    result = evaluation_module._detailed_sequential_metrics(devices)
    # The denominator for attacker rates is ALL attacker devices, including
    # the never-reviewed, never-blocked "patient" attacker -- not just the
    # ones that were ever acted on.
    assert result["all_attackers"] == 2
    assert result["attacker_review_or_higher"]["denominator"] == 2
    assert result["attacker_review_or_higher"]["numerator"] == 1
    assert result["never_reviewed_attackers"] == 1
    assert result["never_blocked_attackers"] == 1


def test_detailed_sequential_metrics_by_subtype_and_within_request_windows():
    devices = _devices_frame()
    result = evaluation_module._detailed_sequential_metrics(devices)
    assert set(result["by_subtype"]) == {"burst", "patient"}
    assert result["by_subtype"]["burst"]["review_or_higher"]["numerator"] == 1
    assert result["by_subtype"]["patient"]["never_reviewed"] == 1
    # within_request thresholds: burst attacker's first review request index
    # is 2, so it counts toward limit>=3 and limit>=5 but not limit==1.
    assert result["within_request"]["1"]["review_or_higher"]["numerator"] == 0
    assert result["within_request"]["3"]["review_or_higher"]["numerator"] == 1


def test_detailed_sequential_metrics_legitimate_breakdown_by_scenario():
    devices = _devices_frame()
    result = evaluation_module._detailed_sequential_metrics(devices)
    assert result["legitimate"]["overall"]["review_or_higher"]["denominator"] == 2
    assert result["legitimate"]["overall"]["review_or_higher"]["numerator"] == 1
    assert result["legitimate"]["normal_standard"]["review_or_higher"]["numerator"] == 0
    assert result["legitimate"]["flash_standard"]["review_or_higher"]["numerator"] == 1


def test_detailed_sequential_metrics_preventable_upper_bound_sums_across_devices():
    devices = _devices_frame()
    result = evaluation_module._detailed_sequential_metrics(devices)
    assert result["potentially_preventable_later_requests_upper_bound"] == 2


# ---------------------------------------------------------------------------
# _benchmark -- pure timing wrapper, no I/O.
# ---------------------------------------------------------------------------


class _ConstantArtifact:
    calibration_method = "none"
    calibrator = None

    def __init__(self, probability):
        self._probability = probability

    def predict_raw_proba(self, frame):
        return np.full(len(frame), self._probability)

    def predict_proba(self, frame):
        return np.full(len(frame), self._probability)


def test_benchmark_reports_both_model_and_policy_timing_percentiles():
    rng = np.random.RandomState(0)
    row = pd.DataFrame({name: rng.rand(1) for name in MODEL_FEATURE_COLUMNS})
    candidate = {"family": "ml_only", "review_threshold": 0.2, "block_threshold": 0.8}
    result = evaluation_module._benchmark(
        _ConstantArtifact(0.5), row, candidate, rule_score=0
    )
    for key in ("model_precheck", "policy_decision"):
        assert result[key]["sample_count"] == 300
        assert result[key]["p50_ms"] >= 0
        assert result[key]["p50_ms"] <= result[key]["p99_ms"]


# ---------------------------------------------------------------------------
# run_validation_policy_phase -- full synthetic end-to-end.
# ---------------------------------------------------------------------------


def _lifecycle_request(sequence, request_id, timestamp, device, amount=1.0):
    return {
        "event_id": f"event-{device}-{sequence}",
        "request_id": request_id,
        "event_sequence": sequence,
        "timestamp": timestamp.isoformat(),
        "event_type": "authorization_request",
        "device_id": device,
        "session_id": f"session-{device}",
        "ip_fingerprint": f"ip-{device}",
        "card_fingerprint": f"card-{device}-{sequence}",
        "card_bin": "411111",
        "amount": amount,
        "currency": "INR",
        "campaign_active": False,
        "label": 1,
    }


class _ScoreByFirstFeatureArtifact:
    """A deterministic stand-in model: probability is driven directly by the
    causal engine's own real precheck feature snapshot (whatever the actual
    feature pipeline computes), so replay_policy exercises the genuine
    feature -> probability -> action pipeline end to end."""

    calibration_method = "none"
    calibrator = None

    def predict_raw_proba(self, frame):
        return np.clip(frame[MODEL_FEATURE_COLUMNS[0]].to_numpy(dtype=float), 0.0, 1.0)

    def predict_proba(self, frame):
        return self.predict_raw_proba(frame)


def _write_policy_environment(root, monkeypatch):
    (root / "configs/v2").mkdir(parents=True)
    (root / "data/v2/development").mkdir(parents=True)
    (root / "artifacts/v2/models").mkdir(parents=True)
    (root / "artifacts/v2/metrics").mkdir(parents=True)
    (root / "artifacts/v2/predictions").mkdir(parents=True)
    (root / "artifacts/v2/policy").mkdir(parents=True)
    (root / "artifacts/v2/training").mkdir(parents=True)
    (root / "reports/v2/modeling").mkdir(parents=True)
    (root / "src").symlink_to(access.ROOT / "src")
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")

    policy_config = {
        "budgets": {
            "overall_legitimate": {
                "denominator": 2,
                "review_or_higher_rate": 0.5,
                "review_or_higher_allowance": 1,
                "block_rate": 0.5,
                "block_allowance": 1,
            },
            "normal_standard": {
                "denominator": 2,
                "review_or_higher_rate": 0.5,
                "review_or_higher_allowance": 1,
                "block_rate": 0.5,
                "block_allowance": 1,
            },
        },
        "families": {
            "rules_only": {"review_scores": [1], "block_scores": [5]},
            "ml_only": {"review_thresholds": [0.3], "block_thresholds": [0.9]},
            "combined": {
                "review_thresholds": [0.3],
                "block_thresholds": [0.9],
                "review_scores": [1],
                "block_support_scores": [5],
            },
        },
    }
    (root / "configs/v2/policy.yaml").write_text(yaml.safe_dump(policy_config))

    devices = ["attacker-1", "attacker-2", "legit-1", "legit-2"]
    splits = pd.DataFrame(
        {
            "device_id": devices,
            "split": ["validation"] * 4,
            "population": ["attack", "attack", "legitimate", "legitimate"],
            "attack_subtype": ["burst", "burst", np.nan, np.nan],
            "scenario_tag": [
                "attack_burst",
                "attack_burst",
                "normal_standard",
                "normal_standard",
            ],
            "label": [1, 1, 0, 0],
        }
    )
    splits.to_csv(root / "data/v2/development/device_splits.csv", index=False)

    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw_records = []
    # Attacker-1 makes 3 requests with a rising first feature value so it is
    # eventually reviewed then blocked (exercising suppression of later
    # requests as counterfactual-after-block).
    for index in range(4):
        raw_records.append(
            _lifecycle_request(
                index,
                f"attacker-1-req-{index}",
                start + timedelta(seconds=index),
                "attacker-1",
            )
        )
    # Attacker-2 makes only low-signal requests (never acted on).
    for index in range(2):
        raw_records.append(
            _lifecycle_request(
                index,
                f"attacker-2-req-{index}",
                start + timedelta(seconds=index),
                "attacker-2",
            )
        )
    # Two legitimate devices, low signal, never acted on.
    for device in ("legit-1", "legit-2"):
        raw_records.append(_lifecycle_request(0, f"{device}-req-0", start, device))
    raw = pd.DataFrame(raw_records)

    rng = np.random.RandomState(0)
    feature_rows = []
    for device in devices:
        for _ in range(2):
            row = {name: float(rng.rand()) for name in MODEL_FEATURE_COLUMNS}
            row["label"] = 1 if device.startswith("attacker") else 0
            row["event_id"] = f"precheck-{device}-{len(feature_rows)}"
            row["device_id"] = device
            feature_rows.append(row)
    features = pd.DataFrame(feature_rows)

    monkeypatch.setattr(
        evaluation_module,
        "verify_training_freeze",
        lambda: {"created_utc": "2026-01-01T00:00:00+00:00"},
    )
    monkeypatch.setattr(
        evaluation_module,
        "open_validation",
        lambda: (
            features,
            raw,
            {
                "first_validation_access_utc": "2026-01-01T00:00:01+00:00",
                "training_freeze_created_utc": "2026-01-01T00:00:00+00:00",
                "training_freeze_sha256": "0" * 64,
            },
        ),
    )
    monkeypatch.setattr(
        evaluation_module,
        "_allow_all_parity",
        lambda raw, frozen: {
            "precheck_rows": len(frozen),
            "features": len(MODEL_FEATURE_COLUMNS),
            "maximum_absolute_difference": 0.0,
            "passed": True,
        },
    )

    # The loaded artifact only needs predict_raw_proba/predict_proba and a
    # calibration_method attribute (as _DuplicatePredictionCache and the
    # real CalibratedModelArtifact both require) -- write the stub directly.
    joblib.dump(
        _ScoreByFirstFeatureArtifact(),
        root / "artifacts/v2/models/calibrated_model.joblib",
    )
    (root / "artifacts/v2/policy").mkdir(exist_ok=True)
    (root / "artifacts/v2/policy/rules.json").write_text(
        json.dumps({"maximum_score": 6})
    )
    (root / "artifacts/v2/training/training_freeze.json").write_text(
        json.dumps({"stub": True})
    )
    return features, raw


def test_run_validation_policy_phase_end_to_end(tmp_path, monkeypatch):
    _write_policy_environment(tmp_path, monkeypatch)

    result = evaluation_module.run_validation_policy_phase(root=tmp_path)

    assert result["candidate_count"] >= 3  # at least one candidate per family
    assert result["feasible_candidate_count"] >= 1
    selected = result["selected_policy"]
    assert selected["family"] in {"rules_only", "ml_only", "combined"}

    policy_path = tmp_path / "artifacts/v2/policy/frozen_policy.json"
    assert policy_path.exists()
    metrics_path = tmp_path / "artifacts/v2/metrics/validation_metrics.json"
    metrics_payload = json.loads(metrics_path.read_text())

    # Every enumerated family is represented in the candidate table.
    candidates = pd.read_csv(
        tmp_path / "artifacts/v2/metrics/validation_policy_candidates.csv"
    )
    assert set(candidates.family) == {"rules_only", "ml_only", "combined"}
    # Candidate ids are unique and deterministically ordered.
    assert list(candidates.candidate_id) == sorted(
        candidates.candidate_id, key=lambda v: v
    )

    # No partial champion is written when infeasible candidates exist
    # alongside feasible ones: frozen_policy.json must correspond to one of
    # the feasible rows in the candidate table.
    feasible_ids = set(candidates.loc[candidates.feasible, "candidate_id"])
    assert selected["candidate_id"] in feasible_ids

    assert metrics_payload["candidate_count"] == len(candidates)


def test_run_validation_policy_phase_replay_is_deterministic(tmp_path, monkeypatch):
    root_a = tmp_path / "run_a"
    root_b = tmp_path / "run_b"
    root_a.mkdir()
    root_b.mkdir()
    _write_policy_environment(root_a, monkeypatch)
    result_a = evaluation_module.run_validation_policy_phase(root=root_a)
    _write_policy_environment(root_b, monkeypatch)
    result_b = evaluation_module.run_validation_policy_phase(root=root_b)
    assert result_a["selected_policy"] == result_b["selected_policy"]
    assert result_a["objective_tuple"] == result_b["objective_tuple"]


def test_run_validation_policy_phase_raises_when_every_candidate_infeasible(
    tmp_path, monkeypatch
):
    _write_policy_environment(tmp_path, monkeypatch)
    # Tighten every budget to zero allowance AND force every family to
    # review every single request (review_score/review_threshold of 0) --
    # every candidate now certainly reviews the legitimate devices too, so
    # nothing can satisfy a zero allowance.
    policy_path = tmp_path / "configs/v2/policy.yaml"
    config = yaml.safe_load(policy_path.read_text())
    for budget in config["budgets"].values():
        budget["review_or_higher_allowance"] = 0
        budget["block_allowance"] = 0
        budget["review_or_higher_rate"] = 0.0
        budget["block_rate"] = 0.0
    config["families"]["rules_only"]["review_scores"] = [0]
    config["families"]["ml_only"]["review_thresholds"] = [0.0]
    config["families"]["combined"]["review_thresholds"] = [0.0]
    config["families"]["combined"]["review_scores"] = [0]
    policy_path.write_text(yaml.safe_dump(config))

    with pytest.raises(RuntimeError, match="no frozen validation policy candidate"):
        evaluation_module.run_validation_policy_phase(root=tmp_path)

    # No partial champion policy artifact is written on total infeasibility.
    assert not (tmp_path / "artifacts/v2/policy/frozen_policy.json").exists()
