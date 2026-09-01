"""Dataset v3: persistent customers, episodes, and the defects it fixes.

Most tests run on a small config fixture rather than the real dataset, so the
suite stays fast. The tests that assert preservation (Dataset V2, the Blind
v1.1 freeze bundle) read the real repository state.
"""

from __future__ import annotations

import ast
import copy
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.features.batch import build_feature_table
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.generator_v3 import (
    build_manifest,
    generate_dataset_v3,
    load_config,
)
from card_testing_sentinel.ml.population_v3 import (
    DatasetV3Error,
    build_covering_merchants,
    build_customers,
)
from card_testing_sentinel.ml.validation import OUTCOME_ONLY_FIELDS, ValidationReport
from card_testing_sentinel.ml.validation_v3 import (
    check_customer_id_presence,
    check_customer_structure,
    check_label_bookkeeping,
    check_merchant_realization,
    check_split_identity_separation,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/dataset_v3.yaml"
V3 = ROOT / "data/generated/development_v3"


@pytest.fixture(scope="module")
def small_config() -> dict:
    config = copy.deepcopy(load_config(CONFIG))
    config["splits"]["train"]["devices"] = 500
    config["splits"]["validation"]["devices"] = 250
    return config


@pytest.fixture(scope="module")
def bundle(small_config) -> dict:
    return generate_dataset_v3(small_config)


@pytest.fixture(scope="module")
def features(bundle) -> pd.DataFrame:
    return build_feature_table(bundle["raw_events"], bundle["labels"])


# --- persistent customer identity (the whole point of v3) -------------------


def test_a_customer_persists_across_episodes(bundle):
    """V2's defect: a customer id existed for exactly one short run."""
    raw = bundle["raw_events"]
    requests = raw.loc[raw.event_type.eq("authorization_request")].copy()
    requests["ts"] = pd.to_datetime(requests.timestamp, format="ISO8601")
    identified = requests.dropna(subset=["customer_id"])
    span = identified.groupby("customer_id").ts.agg(["min", "max"])
    days = (span["max"] - span["min"]).dt.total_seconds() / 86400.0
    assert (days > 1.0).sum() > 0, "no customer history spans more than a day"
    assert days.max() > 7.0, "no customer history reaches a week"


def test_customers_span_several_devices_in_both_populations(bundle):
    # The fixture is a fraction of the real dataset, so the per-population
    # floor is scaled down; the real dataset is checked by the pipeline gate.
    gates = copy.deepcopy(load_config(CONFIG)["gates"])
    gates["multi_device_customers"]["min_per_population"] = 5
    report = ValidationReport()
    check_customer_structure(gates, bundle["labels"], report)
    assert report.passed, report.failures
    structure = report.summary["customer_structure"]
    assert structure["multi_device_attack"] > 0
    assert structure["multi_device_legitimate"] > 0


def test_a_customer_is_never_both_populations_or_both_splits(bundle):
    devices = bundle["labels"].drop_duplicates("device_id")
    grouped = devices.groupby("customer_id").agg(
        labels=("label", "nunique"), splits=("split", "nunique")
    )
    assert (grouped.labels == 1).all()
    assert (grouped.splits == 1).all()


def test_customers_join_inside_the_window_and_carry_no_injected_history():
    """Tenure must emerge from generated events, never from an attribute."""
    config = load_config(CONFIG)
    start = datetime.fromisoformat("2026-01-05T00:00:00+00:00")
    customers = build_customers(np.random.default_rng(1), config, 200, start, 100, "x_")
    joined = [c.joined_at for c in customers]
    assert min(joined) >= start
    fraction = float(config["customers"]["join_window_fraction"])
    assert max(joined) <= start + pd.Timedelta(days=100 * fraction)
    # no success/failure/tenure counter is stored on the profile
    fields = set(vars(customers[0]))
    assert not {
        name for name in fields if any(w in name for w in ("success", "fail", "count"))
    }


# --- the defects v3 fixes ---------------------------------------------------


def test_every_labelled_device_actually_transacted(bundle):
    """Blind v1.1 labelled 109 attack devices that never made a request."""
    report = ValidationReport()
    check_label_bookkeeping(bundle["raw_events"], bundle["labels"], report)
    assert report.passed, report.failures
    assert report.summary["label_bookkeeping"]["silent_devices"] == 0


def test_the_bookkeeping_gate_catches_a_silent_device(bundle):
    """The gate must fail on a device that never transacted, not shrug."""
    labels = bundle["labels"]
    ghost = labels.iloc[[0]].copy()
    ghost["device_id"] = "ghost_device"
    report = ValidationReport()
    check_label_bookkeeping(bundle["raw_events"], pd.concat([labels, ghost]), report)
    assert not report.passed
    assert any("never transacted" in failure for failure in report.failures)


def test_every_declared_merchant_kind_is_realized(bundle, small_config):
    report = ValidationReport()
    check_merchant_realization(small_config, bundle["labels"], report)
    assert report.passed, report.failures
    declared = set(small_config["merchants"]["kinds"])
    assert declared == set(report.summary["merchant_realization"]["realized"])
    assert "travel" in declared  # the kind Dataset V2 declared and never built


def test_more_merchant_kinds_than_slots_is_refused(small_config):
    broken = copy.deepcopy(small_config["merchants"])
    broken["count"] = 2
    with pytest.raises(DatasetV3Error, match="every declared kind"):
        build_covering_merchants(np.random.default_rng(0), broken)


def test_a_scenario_with_no_compatible_merchant_fails_generation(small_config):
    """Never silently fall back to the full merchant pool."""
    broken = copy.deepcopy(small_config)
    broken["scenarios"]["subscription_dunning"]["merchant_kinds"] = ["nonexistent"]
    with pytest.raises(DatasetV3Error, match="none was realized"):
        generate_dataset_v3(broken)


def test_constrained_scenarios_appear_only_on_declared_kinds(bundle, small_config):
    devices = bundle["labels"].drop_duplicates("device_id")
    for name, spec in small_config["scenarios"].items():
        declared = spec.get("merchant_kinds")
        if not declared:
            continue
        used = set(devices.loc[devices.scenario.eq(name), "merchant_kind"])
        assert used <= set(declared), f"{name} appeared on {used - set(declared)}"


# --- customer_id presence must not be a shortcut ----------------------------


def test_customer_id_presence_does_not_separate_the_populations(bundle):
    report = ValidationReport()
    check_customer_id_presence(
        load_config(CONFIG)["gates"], bundle["raw_events"], bundle["labels"], report
    )
    assert report.passed, report.failures
    presence = report.summary["customer_id_presence"]
    assert presence["attack"] > 0.2, "attacks must sometimes carry a customer id"
    assert presence["legitimate"] < 1.0, "guests must exist"


def test_guest_families_never_carry_a_customer_id(bundle):
    raw = bundle["raw_events"]
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    devices = bundle["labels"].drop_duplicates("device_id")[["device_id", "scenario"]]
    tagged = requests.merge(devices, on="device_id", how="left")
    guest = tagged.loc[tagged.scenario.eq("cold_start_guest")]
    assert len(guest) > 0
    assert guest.customer_id.isna().all()


def test_login_is_decided_per_visit_not_per_request(bundle):
    """A shopper does not log in and out between two clicks."""
    raw = bundle["raw_events"]
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    per_session = requests.groupby("session_id").customer_id.apply(
        lambda values: values.notna().nunique()
    )
    assert (per_session == 1).all(), "customer_id presence flipped inside a session"


# --- causal generation, unchanged -------------------------------------------


def test_the_generator_emits_raw_events_not_features(bundle):
    raw = bundle["raw_events"]
    assert set(raw.event_type) <= {
        "authorization_request",
        "authorization_outcome",
        "checkout_completion",
    }
    assert not set(MODEL_FEATURES) & set(raw.columns)


def test_request_events_carry_no_card_or_outcome_metadata(bundle):
    requests = bundle["raw_events"].pipe(
        lambda frame: frame.loc[frame.event_type.eq("authorization_request")]
    )
    for field in OUTCOME_ONLY_FIELDS:
        assert requests[field].isna().all(), field


def test_features_come_from_the_runtime_engine(bundle, features):
    requests = bundle["raw_events"].event_type.eq("authorization_request").sum()
    assert len(features) == requests
    assert [n for n in features.columns if n in set(MODEL_FEATURES)] == list(
        MODEL_FEATURES
    )
    assert features.loc[:, list(MODEL_FEATURES)].notna().all().all()


def test_no_branch_anywhere_keys_on_the_label():
    """The label may only be read from the scenario's declared population."""
    source = (ROOT / "src/card_testing_sentinel/ml/generator_v3.py").read_text()
    tree = ast.parse(source)
    forbidden = {"label", "population", "is_attack", "scenario_label"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Exact identifiers only: `not actor_labels` is bookkeeping, not a
        # branch on the label.
        names = {
            inner.id for inner in ast.walk(node.test) if isinstance(inner, ast.Name)
        } | {
            inner.attr
            for inner in ast.walk(node.test)
            if isinstance(inner, ast.Attribute)
        }
        leaked = names & forbidden
        assert not leaked, f"branch keys on {leaked}: {ast.unparse(node.test)}"


def test_splits_share_no_identifier(bundle):
    report = ValidationReport()
    check_split_identity_separation(bundle["raw_events"], bundle["labels"], report)
    assert report.passed, report.failures
    assert all(v == 0 for v in report.summary["split_identity_overlap"].values())


def test_validation_opens_after_the_last_training_event(bundle):
    raw = bundle["raw_events"]
    times = pd.to_datetime(raw.timestamp, format="ISO8601")
    train_last = times[raw.split.eq("train")].max()
    validation_first = times[raw.split.eq("validation")].min()
    assert train_last < validation_first


def test_generation_is_deterministic(small_config):
    first = generate_dataset_v3(small_config)
    second = generate_dataset_v3(small_config)
    pd.testing.assert_frame_equal(first["raw_events"], second["raw_events"])
    pd.testing.assert_frame_equal(first["labels"], second["labels"])


def test_the_manifest_records_composition_and_no_metrics(bundle, small_config):
    manifest = build_manifest(small_config, bundle)
    assert manifest["model_trained"] is False
    assert manifest["blind_evaluated"] is False
    assert manifest["spec_version"] == "v3"
    for key in (
        "customer_id_presence",
        "merchant_kinds_realized",
        "merchant_instances_per_kind",
        "scenario_devices",
        "splits",
    ):
        assert key in manifest, key
    metric_words = ("recall", "precision", "risk_score", "pr_auc", "roc_auc", "brier")

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                assert not any(w in key.lower() for w in metric_words), f"{path}.{key}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(manifest)


# --- preservation -----------------------------------------------------------


def test_v3_does_not_touch_the_blind_freeze_bundle():
    """Blind v1.1's generator sources are hashed; v3 must import, never edit."""
    import scripts.freeze_blind_benchmark as freeze

    assert freeze.verify() == [], "Dataset v3 work disturbed the blind freeze"
    v3_modules = {
        "src/card_testing_sentinel/ml/generator_v3.py",
        "src/card_testing_sentinel/ml/population_v3.py",
        "src/card_testing_sentinel/ml/scenarios_v3.py",
        "src/card_testing_sentinel/ml/validation_v3.py",
    }
    assert not v3_modules & set(freeze.BLIND_GENERATOR_SOURCES)


def test_dataset_v2_is_still_present_and_separate():
    """v3 replaces V2 as the development corpus; it does not delete it."""
    v2 = ROOT / "data/generated/development"
    assert (v2 / "raw_events.csv").is_file()
    assert (v2 / "manifest.json").is_file()
    assert V3.resolve() != v2.resolve()


def test_v3_never_imports_the_v2_generator():
    """Separate lineage: a v3 change must not be able to alter Dataset V2."""
    source = (ROOT / "src/card_testing_sentinel/ml/generator_v3.py").read_text()
    assert "ml.generator" not in source
    assert "ml import generator" not in source
