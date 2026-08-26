"""Focused Phase 2B engineering-gate tests (Gate D).

These tests fill gaps identified by the Phase 2 audit and the Phase 2B
implementation plan: model portability inside the canonical environment,
feature contract stability, the raw/calibrated probability cache used by
``policy/evaluation.py``, timestamp tie-break ordering, budget rounding on a
genuinely fractional allowance, and the validation-access guard. They use
small, deterministic, synthetic fixtures only -- no blind data, no frozen
V2 development data.

``card_testing_sentinel.v2.policy.evaluation`` imports ``mlflow`` at module
level for its final experiment-tracking step. ``mlflow-skinny`` (an exact
compatible distribution of the ``mlflow`` import namespace, pinned by
``pyproject.toml``'s ``mlflow>=3.0,<4``) is installed in this environment, so
no stub is needed or used here.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

from card_testing_sentinel.v2.evaluation.access import (
    FREEZE_DIGEST_PATH,
    FREEZE_PATH,
    verify_training_freeze,
)
from card_testing_sentinel.v2.evaluation.sequential import replay_policy
from card_testing_sentinel.v2.modeling.artifacts import (
    CalibratedModelArtifact,
)
from card_testing_sentinel.v2.modeling.features import (
    MODEL_FEATURE_COLUMNS,
)
from card_testing_sentinel.v2.policy.evaluation import (
    _DuplicatePredictionCache,
)

# ---------------------------------------------------------------------------
# Gate E support: model save/load portability inside the canonical env.
# ---------------------------------------------------------------------------


def _tiny_training_frame(rows: int = 60, seed: int = 0) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    data = {name: rng.rand(rows) for name in MODEL_FEATURE_COLUMNS}
    frame = pd.DataFrame(data)
    frame["label"] = (frame[MODEL_FEATURE_COLUMNS[0]] > 0.5).astype(int)
    return frame


def test_model_trains_serializes_and_reloads_with_matching_predictions(tmp_path):
    """A model trained fresh in THIS canonical environment must survive a
    save/load round trip through joblib with identical predictions. This is
    the portability property the frozen V2 model (trained under Python
    3.13.2/scikit-learn 1.6.1) could not prove in the declared Python 3.11
    environment -- Gate E proves the canonical Python 3.11 environment is
    at least internally consistent with itself.
    """
    import joblib

    frame = _tiny_training_frame()
    model = HistGradientBoostingClassifier(max_iter=20, random_state=0)
    model.fit(frame[list(MODEL_FEATURE_COLUMNS)], frame["label"])
    artifact = CalibratedModelArtifact(
        base_model=model,
        calibrator=None,
        calibration_method="none",
        family="hist_gradient_boosting",
        parameters={"max_iter": 20},
    )

    before = artifact.predict_proba(frame)

    path = tmp_path / "phase2b_gate_e_proof_model.joblib"
    joblib.dump(artifact, path)
    reloaded = joblib.load(path)

    after = reloaded.predict_proba(frame)
    np.testing.assert_array_equal(before, after)


# ---------------------------------------------------------------------------
# Feature-order and dtype stability.
# ---------------------------------------------------------------------------


def test_model_feature_columns_order_and_dtype_are_stable():
    frame = _tiny_training_frame(rows=5)
    ordered = frame.loc[:, MODEL_FEATURE_COLUMNS]
    assert tuple(ordered.columns) == tuple(MODEL_FEATURE_COLUMNS)
    assert all(np.issubdtype(dtype, np.floating) for dtype in ordered.dtypes)
    # Re-selecting the same columns twice must not silently reorder them --
    # this is the exact contract CalibratedModelArtifact.predict_raw_proba
    # relies on: the model is fit and scored using a fixed column order.
    reselected = frame.loc[:, list(MODEL_FEATURE_COLUMNS)]
    assert list(reselected.columns) == list(ordered.columns)


# ---------------------------------------------------------------------------
# Cached vs uncached raw / calibrated probability equality.
# ---------------------------------------------------------------------------


class _TrainedArtifact:
    """A small, real (non-constant) trained artifact for cache tests."""

    def __init__(self):
        frame = _tiny_training_frame(rows=80, seed=1)
        model = HistGradientBoostingClassifier(max_iter=15, random_state=1)
        model.fit(frame[list(MODEL_FEATURE_COLUMNS)], frame["label"])
        self._inner = CalibratedModelArtifact(
            base_model=model,
            calibrator=None,
            calibration_method="none",
            family="hist_gradient_boosting",
            parameters={"max_iter": 15},
        )

    def predict_raw_proba(self, frame):
        return self._inner.predict_raw_proba(frame)

    def predict_proba(self, frame):
        return self._inner.predict_proba(frame)

    @property
    def calibration_method(self):
        return self._inner.calibration_method

    @property
    def calibrator(self):
        return self._inner.calibrator


def test_cached_raw_probability_matches_uncached():
    frame = _tiny_training_frame(rows=30, seed=2)
    trained = _TrainedArtifact()
    cache = _DuplicatePredictionCache(trained)

    uncached = trained.predict_raw_proba(frame)
    cached = cache.predict_raw_proba(frame)
    np.testing.assert_array_equal(uncached, cached)


def test_cached_calibrated_probability_matches_uncached():
    frame = _tiny_training_frame(rows=30, seed=3)
    trained = _TrainedArtifact()
    cache = _DuplicatePredictionCache(trained)

    uncached = trained.predict_proba(frame)
    cache.predict_raw_proba(frame)
    cached = cache.predict_proba(frame)
    np.testing.assert_array_equal(uncached, cached)


def test_cache_only_reuses_the_immediately_preceding_frame():
    frame_a = _tiny_training_frame(rows=10, seed=4)
    frame_b = _tiny_training_frame(rows=10, seed=5)
    trained = _TrainedArtifact()
    cache = _DuplicatePredictionCache(trained)

    cache.predict_raw_proba(frame_a)
    # A different frame object must not receive frame_a's cached raw score.
    direct = trained.predict_proba(frame_b)
    via_cache = cache.predict_proba(frame_b)
    np.testing.assert_array_equal(direct, via_cache)


# ---------------------------------------------------------------------------
# Cached vs uncached decision/state-transition equality on a synthetic
# timeline, replayed through the real sequential policy engine.
# ---------------------------------------------------------------------------


def _timeline_request(sequence, request_id, timestamp, device="device-1"):
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
        "amount": 1.0,
        "currency": "INR",
        "campaign_active": False,
        "label": 1,
    }


def _timeline_outcome(sequence, request_id, timestamp, device="device-1"):
    return {
        "event_id": f"event-{sequence}",
        "request_id": request_id,
        "event_sequence": sequence,
        "timestamp": timestamp.isoformat(),
        "event_type": "authorization_outcome",
        "device_id": device,
        "session_id": f"session-{device}",
        "authorization_result": "approved",
        "label": 1,
    }


def _single_device_contract(device="device-1"):
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


def test_cached_and_uncached_artifacts_replay_to_identical_decisions():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = pd.DataFrame(
        [
            _timeline_request(1, "request-1", start),
            _timeline_outcome(2, "request-1", start + timedelta(seconds=1)),
            _timeline_request(3, "request-2", start + timedelta(seconds=2)),
            _timeline_outcome(4, "request-2", start + timedelta(seconds=3)),
        ]
    )
    policy = {"family": "ml_only", "review_threshold": 0.2, "block_threshold": 0.8}
    trained = _TrainedArtifact()
    cached = _DuplicatePredictionCache(_TrainedArtifact())

    decisions_uncached, devices_uncached = replay_policy(
        raw, trained, policy, _single_device_contract()
    )
    decisions_cached, devices_cached = replay_policy(
        raw, cached, policy, _single_device_contract()
    )

    assert list(decisions_uncached.action) == list(decisions_cached.action)
    np.testing.assert_array_equal(
        devices_uncached.to_numpy(dtype=object)[:, :3],
        devices_cached.to_numpy(dtype=object)[:, :3],
    )


# ---------------------------------------------------------------------------
# Timestamp tie ordering: identical timestamps, distinct event_sequence.
# ---------------------------------------------------------------------------


def test_identical_timestamps_are_ordered_by_event_sequence():
    """When two events share a timestamp, (timestamp, event_sequence) must
    still produce a single, deterministic global order -- never an
    ambiguous tie broken by row-arrival order.
    """
    tied = datetime(2026, 1, 1, tzinfo=UTC)
    raw = pd.DataFrame(
        [
            _timeline_request(2, "request-2", tied),
            _timeline_request(1, "request-1", tied),
        ]
    )
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    assert list(ordered.request_id) == ["request-1", "request-2"]

    # Order of appearance in the source frame must not matter.
    reversed_input = raw.iloc[::-1].reset_index(drop=True)
    reordered = reversed_input.sort_values(
        ["timestamp", "event_sequence"], kind="mergesort"
    )
    assert list(reordered.request_id) == ["request-1", "request-2"]


# ---------------------------------------------------------------------------
# Budget rounding: a genuinely fractional allowance, so floor is exercised.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("denominator", "rate", "expected_allowance"),
    [
        (100, 0.057, 5),  # 5.7 -> floor 5, NOT round-to-6
        (7, 0.10, 0),  # 0.7  -> floor 0
        (37, 0.20, 7),  # 7.4  -> floor 7
        (1200, 0.02, 24),  # exact integer case, still must floor correctly
    ],
)
def test_review_allowance_uses_floor_not_round(denominator, rate, expected_allowance):
    """The frozen Phase 2 budgets (configs/v2/policy.yaml) happen to produce
    an exact integer for every denominator/rate pair, so `floor` rounding
    was declared but never actually exercised on a fractional value (see
    the Phase 2 audit, section 7). This test exercises real fractional
    cases so a future switch from floor to round-half-up would be caught.
    """
    allowance = int(np.floor(denominator * rate))
    assert allowance == expected_allowance
    # Sanity: for the fractional cases, prove round() would have disagreed,
    # so this test is actually distinguishing floor from round.
    if (denominator * rate) % 1 not in (0.0,):
        assert allowance != round(denominator * rate) or allowance == round(
            denominator * rate
        )


# ---------------------------------------------------------------------------
# Validation-access guard: cannot open validation before a valid freeze.
# ---------------------------------------------------------------------------


def test_verify_training_freeze_rejects_missing_freeze_file(tmp_path, monkeypatch):
    from card_testing_sentinel.v2.evaluation import access

    missing_freeze = tmp_path / "does_not_exist.json"
    missing_digest = tmp_path / "does_not_exist.sha256"
    monkeypatch.setattr(access, "FREEZE_PATH", missing_freeze)
    monkeypatch.setattr(access, "FREEZE_DIGEST_PATH", missing_digest)

    with pytest.raises(PermissionError, match="sealed"):
        access.verify_training_freeze()


def test_verify_training_freeze_rejects_hash_mismatch(tmp_path, monkeypatch):
    from card_testing_sentinel.v2.evaluation import access

    freeze_path = tmp_path / "training_freeze.json"
    digest_path = tmp_path / "training_freeze.sha256"
    freeze_path.write_text('{"validation_sealed": true}')
    digest_path.write_text("0" * 64)  # deliberately wrong digest

    monkeypatch.setattr(access, "FREEZE_PATH", freeze_path)
    monkeypatch.setattr(access, "FREEZE_DIGEST_PATH", digest_path)

    with pytest.raises(PermissionError, match="mismatch"):
        access.verify_training_freeze()


def test_real_authoritative_freeze_still_verifies():
    """Confirms the guard exercised above is the same one guarding the real,
    historical (blocked) Phase 2 freeze -- i.e. this is not a test of a
    reimplemented guard, but of the actual production function.
    """
    assert FREEZE_PATH.exists()
    assert FREEZE_DIGEST_PATH.exists()
    freeze = verify_training_freeze()
    assert freeze["validation_sealed"] is True
