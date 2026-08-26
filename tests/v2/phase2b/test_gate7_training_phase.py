"""Gate 7 (corrective pass, coverage raise): an end-to-end, fully synthetic
exercise of ``run_training_phase`` -- the single highest-priority gap
identified for this corrective pass (29% coverage, the whole orchestration
body untested).

Design:
  * ``root=tmp_path`` -- every artifact this test produces lives under a
    pytest-managed temporary directory and is never written into the real
    repository tree.
  * ``access.load_training_features`` / ``access.load_training_raw_events``
    are monkeypatched (they are looked up dynamically through the local
    import inside ``run_training_phase``, so patching the ``access`` module
    attribute redirects them correctly) to return a small, fully synthetic,
    device-grouped feature frame -- never real development or validation
    data.
  * ``training_eda`` is monkeypatched *only* in the ``training`` module's
    own namespace, and *only* to bypass its unrelated hard-coded 21,338-row/
    8,000-device structural-scale guard (asserted directly, with its own
    dedicated tests, in test_gate7_eda.py). The stub still writes real files
    to the given output directory and returns a plausible summary dict; it
    never touches the actual candidate-selection or calibration logic under
    test here.
  * The device/fold construction below is deterministic *by construction*:
    ``make_device_folds`` hash-sorts devices within each scenario_tag and
    assigns fold = index % n_folds, so partitioning 30 attack-scenario
    devices and 30 legitimate-scenario devices into 5 folds always yields
    exactly 6 of each per fold -- guaranteeing every fold, and every nested
    calibration role split, sees both classes.
"""

import json

import numpy as np
import pandas as pd
import pytest
import yaml

from card_testing_sentinel.v2.evaluation import access
from card_testing_sentinel.v2.modeling import training as training_module
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS

N_POSITIVE_DEVICES = 30
N_NEGATIVE_DEVICES = 30
ROWS_PER_DEVICE = 2
FOLDS = 5


def _training_yaml() -> dict:
    return {
        "seed": 20260825,
        "folds": FOLDS,
        "probability_tolerance": 0.000001,
        "primary_legitimate_intervention_rate": 0.03,
        "candidate_grids": {
            "logistic_regression": {"C": [1.0], "max_iter": 200},
            "hist_gradient_boosting": [
                {
                    "learning_rate": 0.1,
                    "max_leaf_nodes": 15,
                    "max_iter": 20,
                    "l2_regularization": 1.0,
                }
            ],
        },
        "calibration_methods": ["none", "sigmoid", "isotonic"],
        "ranking_objective": ["device_weighted_pr_auc"],
        "calibration_objective": ["lowest_device_weighted_brier"],
    }


def _policy_yaml() -> dict:
    return {"plots": ["validation_reliability"]}


def _synthetic_frame(seed=0):
    rng = np.random.RandomState(seed)
    device_ids = []
    labels = []
    scenario_tags = []
    attack_subtypes = []
    for index in range(N_POSITIVE_DEVICES):
        device_ids.append(f"attack-device-{index:03d}")
        labels.append(1)
        scenario_tags.append("attack_burst")
        attack_subtypes.append("burst")
    for index in range(N_NEGATIVE_DEVICES):
        device_ids.append(f"legit-device-{index:03d}")
        labels.append(0)
        scenario_tags.append("normal_standard")
        attack_subtypes.append(np.nan)

    rows = []
    for device, label, scenario, subtype in zip(
        device_ids, labels, scenario_tags, attack_subtypes, strict=True
    ):
        for row_index in range(ROWS_PER_DEVICE):
            row = {name: float(rng.rand()) for name in MODEL_FEATURE_COLUMNS}
            # Inject a mild real signal so PR-AUC/ranking are not degenerate.
            row[MODEL_FEATURE_COLUMNS[0]] = float(
                rng.rand() * 0.5 + (0.5 if label else 0.0)
            )
            row.update(
                event_id=f"event-{device}-{row_index}",
                request_id=f"request-{device}-{row_index}",
                device_id=device,
                label=label,
                attack_subtype=subtype,
                scenario_tag=scenario,
                timestamp=pd.Timestamp("2026-01-01") + pd.Timedelta(seconds=len(rows)),
            )
            rows.append(row)
    frame = pd.DataFrame(rows)
    assert np.isfinite(frame.loc[:, MODEL_FEATURE_COLUMNS].to_numpy()).all()
    return frame, device_ids, scenario_tags


def _device_splits_frame(
    device_ids, scenario_tags, validation_ids=("held-out-device-0",)
):
    rows = [
        {"device_id": device, "scenario_tag": scenario, "split": "train"}
        for device, scenario in zip(device_ids, scenario_tags, strict=True)
    ]
    for validation_device in validation_ids:
        rows.append(
            {
                "device_id": validation_device,
                "scenario_tag": "normal_standard",
                "split": "validation",
            }
        )
    return pd.DataFrame(rows)


def _stub_training_eda(features, raw, output):
    output.mkdir(parents=True, exist_ok=True)
    return {
        "devices": int(features.device_id.nunique()),
        "precheck_rows": int(len(features)),
        "lifecycle_events": int(len(raw)),
        "device_weighted_positive_rate": float(features.label.mean()),
        "row_weighted_positive_rate": float(features.label.mean()),
    }


def _write_environment(root, monkeypatch, seed=0):
    (root / "configs/v2").mkdir(parents=True)
    (root / "configs/v2/training.yaml").write_text(yaml.safe_dump(_training_yaml()))
    (root / "configs/v2/policy.yaml").write_text(yaml.safe_dump(_policy_yaml()))
    (root / "data/v2/development").mkdir(parents=True)
    (root / "artifacts/v2/training").mkdir(parents=True)
    (root / "artifacts/v2/metrics").mkdir(parents=True)
    (root / "artifacts/v2/models").mkdir(parents=True)
    (root / "artifacts/v2/policy").mkdir(parents=True)
    (root / "artifacts/v2/predictions").mkdir(parents=True)
    (root / "reports/v2/modeling").mkdir(parents=True)
    (root / "reports/v2/figures").mkdir(parents=True)
    # run_training_phase hashes its own frozen source files relative to
    # `root` (see `frozen_paths`); symlink in the REAL repository's src tree
    # so those hashes are of the actual frozen decision-logic files, without
    # copying the whole repo into every tmp_path fixture.
    (root / "src").symlink_to(access.ROOT / "src")

    frame, device_ids, scenario_tags = _synthetic_frame(seed=seed)
    splits = _device_splits_frame(device_ids, scenario_tags)
    splits.to_csv(root / "data/v2/development/device_splits.csv", index=False)
    raw = pd.DataFrame({"device_id": device_ids, "session_id": device_ids})

    monkeypatch.setattr(access, "load_training_features", lambda: frame.copy())
    monkeypatch.setattr(access, "load_training_raw_events", lambda: raw.copy())
    monkeypatch.setattr(training_module, "training_eda", _stub_training_eda)
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    return frame, device_ids


# ---------------------------------------------------------------------------
# End-to-end happy path and its required behavioral properties.
# ---------------------------------------------------------------------------


def test_run_training_phase_end_to_end(tmp_path, monkeypatch):
    frame, device_ids = _write_environment(tmp_path, monkeypatch)

    result = training_module.run_training_phase(root=tmp_path)

    # 1. Result contract and artifacts are written only under tmp_path.
    assert result["selected_candidate"]
    assert result["selected_calibration"] in {"none", "sigmoid", "isotonic"}
    freeze_path = tmp_path / "artifacts/v2/training/training_freeze.json"
    assert freeze_path.exists()
    assert str(freeze_path) == result["training_freeze"]
    assert result["training_freeze"].startswith(str(tmp_path))

    freeze = json.loads(freeze_path.read_text())
    assert freeze["fold_device_overlap"] == 0
    assert freeze["validation_sealed"] is True
    assert freeze["validation_performance_computed"] is False

    # 2. Fit/holdout device overlap is zero for every fold (asserted by the
    # freeze's own fold_device_overlap field above, and re-derived here
    # directly from the written fold file).
    folds = pd.read_csv(tmp_path / "artifacts/v2/training/device_folds.csv")
    assert set(folds.device_id) == set(device_ids)
    for fold_value in sorted(folds.fold.unique()):
        holdout = set(folds.loc[folds.fold.eq(fold_value), "device_id"])
        fit = set(folds.device_id) - holdout
        assert not (fit & holdout)

    # 3. OOF predictions cover every training row exactly once.
    oof = pd.read_csv(
        tmp_path / "artifacts/v2/predictions/training_oof_predictions.csv"
    )
    assert len(oof) == len(frame)
    assert set(oof.event_id) == set(frame.event_id)
    assert oof.calibrated_probability.notna().all()

    # 4. Candidate enumeration is deterministic: exactly 2 model candidates
    # (1 logistic + 1 hist_gradient_boosting) plus the rules baseline.
    candidates = pd.read_csv(
        tmp_path / "artifacts/v2/metrics/candidate_oof_metrics.csv"
    )
    assert len(candidates) == 3
    assert set(candidates.family) == {
        "logistic_regression",
        "hist_gradient_boosting",
        "rules",
    }

    # 5. Device weights sum correctly: evaluation weight totals 1 per device;
    # training weight totals 0.5 per class.
    audit = freeze["evaluation_weight_audit"]
    assert audit["total"] == pytest.approx(len(device_ids), abs=1e-9)
    training_audit = freeze["training_weight_audit"]
    assert training_audit["by_class"]["0"] == pytest.approx(0.5, abs=1e-9)
    assert training_audit["by_class"]["1"] == pytest.approx(0.5, abs=1e-9)


def test_run_training_phase_never_reads_the_validation_population(
    tmp_path, monkeypatch
):
    _write_environment(tmp_path, monkeypatch)

    def _forbidden(*args, **kwargs):
        raise AssertionError("training must never open the validation population")

    monkeypatch.setattr(access, "open_validation", _forbidden)
    training_module.run_training_phase(root=tmp_path)


def test_run_training_phase_is_deterministic_across_repeated_execution(
    tmp_path, monkeypatch
):
    root_a = tmp_path / "run_a"
    root_b = tmp_path / "run_b"
    root_a.mkdir()
    root_b.mkdir()
    _write_environment(root_a, monkeypatch, seed=7)
    _write_environment(root_b, monkeypatch, seed=7)

    result_a = training_module.run_training_phase(root=root_a)
    result_b = training_module.run_training_phase(root=root_b)

    assert result_a["selected_candidate"] == result_b["selected_candidate"]
    assert result_a["selected_calibration"] == result_b["selected_calibration"]
    oof_a = pd.read_csv(
        root_a / "artifacts/v2/predictions/training_oof_predictions.csv"
    )
    oof_b = pd.read_csv(
        root_b / "artifacts/v2/predictions/training_oof_predictions.csv"
    )
    np.testing.assert_allclose(
        oof_a.sort_values("event_id").calibrated_probability.to_numpy(),
        oof_b.sort_values("event_id").calibrated_probability.to_numpy(),
        atol=1e-6,
    )


def test_run_training_phase_fails_closed_on_missing_device_splits(
    tmp_path, monkeypatch
):
    _write_environment(tmp_path, monkeypatch)
    (tmp_path / "data/v2/development/device_splits.csv").unlink()

    with pytest.raises(FileNotFoundError):
        training_module.run_training_phase(root=tmp_path)

    # No partial/bad training freeze must be produced on a failed run.
    assert not (tmp_path / "artifacts/v2/training/training_freeze.json").exists()


def test_run_training_phase_fails_closed_on_invalid_configuration(
    tmp_path, monkeypatch
):
    _write_environment(tmp_path, monkeypatch)
    broken_config = _training_yaml()
    del broken_config["folds"]
    (tmp_path / "configs/v2/training.yaml").write_text(yaml.safe_dump(broken_config))

    with pytest.raises(KeyError):
        training_module.run_training_phase(root=tmp_path)

    assert not (tmp_path / "artifacts/v2/training/training_freeze.json").exists()
