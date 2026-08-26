"""Gate 6 (corrective pass): focused, deterministic tests for decision-critical
V2 modules that had little or zero test coverage. Every test exercises the
real, unmodified production functions (frozen or otherwise) against small
synthetic fixtures -- never real development or validation data, and never
fresh-validation or blind data.

Covers, from the corrective task's required list:
  1. Nested calibration has zero device overlap between fitting/eval roles.
  2. Calibration never consumes validation-population data.
  3. Raw/calibrated prediction ordering and shape contracts.
  4. Current-attempt (causal) preauthorization scoring.
  10. Review/block counts use device denominators, not authorization-row ones.
  13. Artifact scoring rejects an incompatible/missing feature contract.
  14. Fresh-validation access guard fails closed (open_validation, not just
      the lower-level verify_training_freeze already covered elsewhere).
Items 5-9, 11, 12 are already covered by
tests/v2/phase2b/test_gate_d_focused.py, tests/v2/unit/test_phase2_contracts.py,
and tests/v2/unit/test_shared_ip_ordering.py and are not duplicated here.
Fold-integrity guards (a closely related decision-critical safety property)
are added as a bonus since folds.py had no dedicated error-path tests.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

from card_testing_sentinel.v2.evaluation.sequential import proportion, replay_policy
from card_testing_sentinel.v2.modeling.artifacts import CalibratedModelArtifact
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.modeling.folds import (
    assert_fold_integrity,
    make_device_folds,
)
from card_testing_sentinel.v2.modeling.training import (
    fit_deployable_artifact,
    nested_calibrated_oof,
)


def _synthetic_calibration_frame(
    devices_per_fold: int = 6, folds: int = 5, seed: int = 0
) -> pd.DataFrame:
    """One row per device (device-level rows are enough for these functions --
    they only ever read device_id/label/fold/MODEL_FEATURE_COLUMNS)."""
    rng = np.random.RandomState(seed)
    rows = []
    device_counter = 0
    for fold in range(folds):
        for _ in range(devices_per_fold):
            row = {name: float(rng.rand()) for name in MODEL_FEATURE_COLUMNS}
            row["device_id"] = f"device-{device_counter}"
            row["fold"] = fold
            row["label"] = int(device_counter % 2 == 0)
            rows.append(row)
            device_counter += 1
    return pd.DataFrame(rows)


LOGISTIC_SPEC = {
    "family": "logistic_regression",
    "parameters": {"C": 1.0, "max_iter": 200},
}


# ---------------------------------------------------------------------------
# 1. Nested calibration device isolation.
# ---------------------------------------------------------------------------


def test_nested_calibrated_oof_reports_zero_overlap_by_construction():
    frame = _synthetic_calibration_frame()
    raw, calibrated, isolation = nested_calibrated_oof(
        frame, LOGISTIC_SPEC, "sigmoid", seed=0
    )
    assert len(isolation) == frame.fold.nunique()
    for record in isolation:
        assert record["all_pairwise_device_overlaps"] == 0
        # Every device must be accounted for exactly once across the three
        # disjoint roles for its own outer fold.
        assert record["base_fit_devices"] + record["calibrator_fit_devices"] + record[
            "evaluation_devices"
        ] == len(frame)


def test_nested_calibrated_oof_fails_closed_on_forced_device_overlap():
    frame = _synthetic_calibration_frame()
    # Force a real isolation violation: make one calibration-fold device
    # secretly share its device_id with a base-fold device.
    tampered = frame.copy()
    victim = tampered.loc[tampered.fold.eq(1)].index[0]
    donor_device = tampered.loc[tampered.fold.eq(2), "device_id"].iloc[0]
    tampered.loc[victim, "device_id"] = donor_device
    with pytest.raises(RuntimeError, match="isolation failed"):
        nested_calibrated_oof(tampered, LOGISTIC_SPEC, "sigmoid", seed=0)


# ---------------------------------------------------------------------------
# 2. Calibration never touches validation-population data.
# ---------------------------------------------------------------------------


def test_calibration_functions_never_call_open_validation(monkeypatch):
    from card_testing_sentinel.v2.evaluation import access

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "calibration/training code must never read the validation population"
        )

    monkeypatch.setattr(access, "open_validation", _forbidden)
    frame = _synthetic_calibration_frame()
    # Both functions must complete using only the passed-in synthetic frame.
    nested_calibrated_oof(frame, LOGISTIC_SPEC, "sigmoid", seed=0)
    fit_deployable_artifact(frame, LOGISTIC_SPEC, "sigmoid", seed=0)


# ---------------------------------------------------------------------------
# 3. Raw/calibrated prediction ordering and shape contracts.
# ---------------------------------------------------------------------------


def test_nested_calibrated_oof_output_shape_and_alignment():
    frame = _synthetic_calibration_frame()
    raw, calibrated, _isolation = nested_calibrated_oof(
        frame, LOGISTIC_SPEC, "isotonic", seed=0
    )
    assert raw.shape == (len(frame),)
    assert calibrated.shape == (len(frame),)
    assert np.all((raw >= 0) & (raw <= 1))
    assert np.all((calibrated >= 0) & (calibrated <= 1))
    # Every row must have been scored by its own outer fold, i.e. no row is
    # left at the zero-initialized default because it was skipped.
    assert not np.array_equal(raw, np.zeros(len(frame)))


def test_fit_deployable_artifact_predictions_are_row_order_stable():
    frame = _synthetic_calibration_frame()
    artifact = fit_deployable_artifact(frame, LOGISTIC_SPEC, "sigmoid", seed=0)
    scored = artifact.predict_proba(frame)
    shuffled = frame.sample(frac=1.0, random_state=99)
    scored_shuffled = artifact.predict_proba(shuffled)
    # Re-aligning the shuffled scores back to the original row order must
    # reproduce the original scores exactly -- predictions are a pure
    # function of each row's own features, not of row position.
    realigned = (
        pd.Series(scored_shuffled, index=shuffled.index).loc[frame.index].to_numpy()
    )
    np.testing.assert_array_equal(scored, realigned)


# ---------------------------------------------------------------------------
# 4. Current-attempt (causal) preauthorization scoring.
# ---------------------------------------------------------------------------


class ConstantArtifact:
    calibration_method = "none"
    calibrator = None

    def __init__(self, probability: float):
        self._probability = probability

    def predict_raw_proba(self, frame):
        return np.full(len(frame), self._probability)

    def predict_proba(self, frame):
        return np.full(len(frame), self._probability)


def _request(sequence, request_id, timestamp, device="device-1", amount=1.0):
    return {
        "event_id": f"event-{sequence}",
        "request_id": request_id,
        "event_sequence": sequence,
        "timestamp": timestamp.isoformat(),
        "event_type": "authorization_request",
        "device_id": device,
        "session_id": f"session-{device}",
        "ip_fingerprint": "ip-1",
        "card_fingerprint": f"card-{sequence}",
        "card_bin": "411111",
        "amount": amount,
        "currency": "INR",
        "campaign_active": False,
        "label": 1,
    }


def _contract(device="device-1"):
    return pd.DataFrame(
        [
            {
                "device_id": device,
                "population": "attack",
                "attack_subtype": "patient",
                "scenario_tag": "attack_patient",
                "label": 1,
            }
        ]
    )


def test_earlier_requests_decision_is_unaffected_by_a_later_request():
    """Preauthorization scoring must use only prior committed state and the
    current request's own known fields -- never information from a request
    that has not happened yet. Two timelines that agree up to and including
    request 1 must produce an identical decision for request 1, regardless
    of what happens afterward.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    policy = {"family": "ml_only", "review_threshold": 0.2, "block_threshold": 0.8}
    artifact = ConstantArtifact(0.5)

    short_timeline = pd.DataFrame([_request(1, "request-1", start)])
    long_timeline = pd.DataFrame(
        [
            _request(1, "request-1", start),
            _request(2, "request-2", start + timedelta(seconds=1)),
            _request(3, "request-3", start + timedelta(seconds=2)),
            _request(4, "request-4", start + timedelta(seconds=3)),
        ]
    )

    decisions_short, _ = replay_policy(short_timeline, artifact, policy, _contract())
    decisions_long, _ = replay_policy(long_timeline, artifact, policy, _contract())

    first_short = decisions_short.loc[decisions_short.request_id.eq("request-1")]
    first_long = decisions_long.loc[decisions_long.request_id.eq("request-1")]
    assert list(first_short.action) == list(first_long.action)


# ---------------------------------------------------------------------------
# 10. Review/block counts use device denominators, not authorization-row ones.
# ---------------------------------------------------------------------------


def test_replay_policy_devices_table_has_one_row_per_device_not_per_request():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    policy = {"family": "ml_only", "review_threshold": 0.9, "block_threshold": 0.99}
    artifact = ConstantArtifact(0.1)
    # One device makes FIVE authorization requests.
    raw = pd.DataFrame(
        [_request(i, f"request-{i}", start + timedelta(seconds=i)) for i in range(5)]
    )
    _decisions, devices = replay_policy(raw, artifact, policy, _contract())
    assert len(devices) == 1  # one device, despite five authorization events
    assert int(devices.loc[0, "label"]) == 1


def test_proportion_denominator_is_device_count_not_event_count():
    # A device-level frame (one row per device, as replay_policy produces),
    # not an authorization-event-level frame.
    devices = pd.DataFrame(
        {
            "device_id": ["d1", "d2", "d3", "d4"],
            "review_or_higher": [True, True, False, False],
        }
    )
    result = proportion(devices, "review_or_higher")
    assert result["denominator"] == 4  # device count
    assert result["numerator"] == 2
    assert result["rate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 13. Artifact scoring rejects an incompatible/missing feature contract.
# ---------------------------------------------------------------------------


def test_artifact_predict_rejects_frame_missing_a_required_feature_column():
    rng = np.random.RandomState(0)
    frame = pd.DataFrame({name: rng.rand(20) for name in MODEL_FEATURE_COLUMNS})
    model = HistGradientBoostingClassifier(max_iter=10, random_state=0)
    model.fit(
        frame[list(MODEL_FEATURE_COLUMNS)],
        (frame[MODEL_FEATURE_COLUMNS[0]] > 0.5).astype(int),
    )
    artifact = CalibratedModelArtifact(
        base_model=model,
        calibrator=None,
        calibration_method="none",
        family="hist_gradient_boosting",
        parameters={"max_iter": 10},
    )
    incompatible = frame.drop(columns=[MODEL_FEATURE_COLUMNS[0]])
    with pytest.raises(KeyError):
        artifact.predict_proba(incompatible)


# ---------------------------------------------------------------------------
# 14. Fresh-validation access guard fails closed (open_validation itself).
# ---------------------------------------------------------------------------


def test_open_validation_fails_closed_when_freeze_is_missing(tmp_path, monkeypatch):
    from card_testing_sentinel.v2.evaluation import access

    monkeypatch.setattr(access, "FREEZE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(access, "FREEZE_DIGEST_PATH", tmp_path / "missing.sha256")

    with pytest.raises(PermissionError, match="sealed"):
        access.open_validation()


# ---------------------------------------------------------------------------
# Bonus: fold-integrity guards (folds.py had no dedicated error-path tests).
# ---------------------------------------------------------------------------


def _training_devices(n=6):
    return pd.DataFrame(
        {
            "device_id": [f"device-{i}" for i in range(n)],
            "scenario_tag": ["normal_standard"] * n,
            "split": ["train"] * n,
        }
    )


def test_make_device_folds_rejects_non_training_split():
    devices = _training_devices()
    devices.loc[0, "split"] = "validation"
    with pytest.raises(ValueError, match="training devices only"):
        make_device_folds(devices)


def test_make_device_folds_rejects_duplicate_device_id():
    devices = pd.concat(
        [_training_devices(), _training_devices().iloc[[0]]], ignore_index=True
    )
    with pytest.raises(ValueError, match="exactly once"):
        make_device_folds(devices)


def test_assert_fold_integrity_rejects_validation_device_leak():
    devices = _training_devices()
    folds = make_device_folds(devices)
    training_ids = set(devices.device_id)
    with pytest.raises(ValueError, match="validation device entered training folds"):
        assert_fold_integrity(folds, training_ids, {"device-0"})


def test_assert_fold_integrity_rejects_missing_training_device():
    devices = _training_devices()
    folds = make_device_folds(devices)
    incomplete_ids = set(devices.device_id) - {"device-0"}
    with pytest.raises(ValueError, match="every and only training device"):
        assert_fold_integrity(folds, incomplete_ids, set())


def test_assert_fold_integrity_accepts_a_correct_partition():
    devices = _training_devices()
    folds = make_device_folds(devices)
    assert_fold_integrity(folds, set(devices.device_id), {"validation-device-x"})
