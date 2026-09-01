"""The blind generator: independence, determinism, lifecycle and guards.

Everything here runs on a small fixture, not the real benchmark. No frozen
model is loaded and no policy is applied, so these tests do not consume
blind v1.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from card_testing_sentinel.features.batch import build_feature_table
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.blind_generator import (
    IDENTITY_PREFIX,
    BlindBenchmarkError,
    assert_after_development,
    assert_not_consumed,
    generate_blind_bundle,
    load_config,
    required_merchant_kinds,
)
from card_testing_sentinel.ml.blind_validation import (
    FORBIDDEN_DEPENDENCIES,
    check_generator_independence,
    check_identity_independence,
    check_merchant_composition,
    check_scenario_merchant_mapping,
    check_temporal_separation,
    shift_report,
    transitive_imports,
)
from card_testing_sentinel.ml.validation import OUTCOME_ONLY_FIELDS, ValidationReport

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs/blind_spec.md"
DEV_MANIFEST = ROOT / "data/generated/development/manifest.json"

ENTRY_MODULES = (
    "card_testing_sentinel.ml.blind_generator",
    "card_testing_sentinel.ml.primitives",
)


@pytest.fixture(scope="module")
def small_config() -> dict:
    config = copy.deepcopy(load_config(ROOT / "configs/blind.yaml"))
    config["population"]["devices"] = 350
    return config


@pytest.fixture(scope="module")
def bundle(small_config) -> dict:
    return generate_blind_bundle(small_config, SPEC, DEV_MANIFEST)


@pytest.fixture(scope="module")
def features(bundle) -> pd.DataFrame:
    raw = bundle["raw_events"].copy()
    raw["split"] = "blind"
    return build_feature_table(raw, bundle["labels"])


# --- independence -----------------------------------------------------------


def test_the_generator_never_reaches_the_model_or_the_policy():
    """The whole benchmark rests on this: the generator cannot have seen the
    system it is meant to test."""
    report = ValidationReport()
    reachable = check_generator_independence(ROOT, ENTRY_MODULES, report)
    assert report.passed, report.failures
    for forbidden in FORBIDDEN_DEPENDENCIES:
        assert not any(module.startswith(forbidden) for module in reachable), forbidden


def test_the_import_walk_is_transitive_not_shallow():
    """A forbidden dependency must not be able to hide one level down."""
    reachable = transitive_imports(ROOT, ENTRY_MODULES)
    # the walk really does follow edges rather than listing the entry points
    assert "card_testing_sentinel.ml.merchants" in reachable
    assert len(reachable) > len(ENTRY_MODULES)
    # and it does catch a forbidden module when one is genuinely reachable
    contaminated = transitive_imports(
        ROOT, ("card_testing_sentinel.services.risk_service",)
    )
    assert any(m.startswith("card_testing_sentinel.policy") for m in contaminated)


def test_blind_identities_are_disjoint_from_development(bundle):
    development_raw = pd.read_csv(
        ROOT / "data/generated/development/raw_events.csv",
        dtype={"card_last4": "string"},
    )
    development_labels = pd.read_csv(ROOT / "data/generated/development/labels.csv")
    report = ValidationReport()
    check_identity_independence(
        bundle["raw_events"],
        bundle["labels"],
        development_raw,
        development_labels,
        report,
    )
    assert report.passed, report.failures
    assert all(value == 0 for value in report.summary["identity_overlap"].values())


def test_every_blind_identity_is_namespaced(bundle):
    raw = bundle["raw_events"]
    for column in ("event_id", "device_id", "session_id", "merchant_id"):
        assert raw[column].dropna().str.startswith(f"{IDENTITY_PREFIX}_").all(), column


# --- temporal ---------------------------------------------------------------


def test_blind_starts_strictly_after_development(bundle):
    development_raw = pd.read_csv(
        ROOT / "data/generated/development/raw_events.csv",
        dtype={"card_last4": "string"},
    )
    report = ValidationReport()
    check_temporal_separation(bundle["raw_events"], development_raw, report)
    assert report.passed, report.failures
    assert report.summary["temporal"]["separation_days"] > 0


def test_generation_refuses_to_overlap_development(bundle):
    """The hard assertion must actually fire, not just be documented."""
    shifted = bundle["raw_events"].copy()
    shifted["timestamp"] = "2026-01-06T00:00:00+00:00"
    with pytest.raises(BlindBenchmarkError, match="floor"):
        assert_after_development(
            shifted, DEV_MANIFEST, datetime.fromisoformat("2026-07-15T00:00:00+00:00")
        )


# --- merchants --------------------------------------------------------------


def test_unseen_merchant_kinds_are_present_and_genuinely_unseen(bundle):
    development_labels = pd.read_csv(ROOT / "data/generated/development/labels.csv")
    report = ValidationReport()
    check_merchant_composition(bundle["labels"], development_labels, report)
    assert report.passed, report.failures
    merchants = report.summary["merchants"]
    assert len(merchants["unseen_kinds"]) >= 2
    assert merchants["devices_on_unseen_kinds"] > 0


def test_every_declared_merchant_kind_is_realized(bundle, small_config):
    """v1.0's defect: kinds were sampled with replacement, so `flash_sale`,
    `travel` and the unseen `ticketing_events` had zero merchants."""
    declared = set(required_merchant_kinds(small_config))
    realized = set(bundle["labels"].merchant_kind)
    assert declared == realized, f"missing kinds: {sorted(declared - realized)}"


def test_every_declared_unseen_merchant_kind_is_realized(bundle, small_config):
    kinds = small_config["merchants"]["kinds"]
    declared_unseen = {n for n, s in kinds.items() if s.get("origin") == "unseen"}
    labels = bundle["labels"]
    realized_unseen = set(
        labels.loc[labels.merchant_origin.eq("unseen"), "merchant_kind"]
    )
    assert declared_unseen == realized_unseen
    assert "ticketing_events" in realized_unseen


def test_constrained_scenarios_use_only_their_declared_kinds(bundle, small_config):
    """The gate that would have caught the silent fallback."""
    report = ValidationReport()
    check_scenario_merchant_mapping(small_config, bundle["labels"], report)
    assert report.passed, report.failures
    mapping = report.summary["scenario_merchant_mapping"]
    assert mapping, "no merchant-constrained scenario was checked"
    for name, entry in mapping.items():
        assert set(entry["used"]) <= set(entry["declared"]), name


def test_a_scenario_with_no_compatible_merchant_fails_generation(small_config):
    """Never silently fall back to the full merchant pool."""
    broken = copy.deepcopy(small_config)
    broken["scenarios"]["campaign_rush"]["merchant_kinds"] = ["kind_that_never_exists"]
    with pytest.raises(BlindBenchmarkError, match="never fall back"):
        generate_blind_bundle(broken, SPEC, DEV_MANIFEST)


def test_more_merchant_kinds_than_slots_is_refused(small_config):
    broken = copy.deepcopy(small_config)
    broken["merchants"]["count"] = 3
    with pytest.raises(BlindBenchmarkError, match="every declared kind"):
        generate_blind_bundle(broken, SPEC, DEV_MANIFEST)


def test_the_missing_kind_gate_actually_fails(bundle, small_config):
    """The validator must notice a kind that is declared but absent."""
    development_labels = pd.read_csv(ROOT / "data/generated/development/labels.csv")
    labels = bundle["labels"]
    thinned = labels.loc[~labels.merchant_kind.eq("ticketing_events")]
    report = ValidationReport()
    check_merchant_composition(thinned, development_labels, report, small_config)
    assert not report.passed
    assert any("ticketing_events" in failure for failure in report.failures)


def test_attack_prevalence_is_hit_at_device_level(bundle, small_config):
    """v1.0 applied the fraction per actor and overshot to 0.291 devices."""
    manifest = bundle["manifest"]
    configured = manifest["configured_attack_device_fraction"]
    assert manifest["realized_attack_device_fraction"] == pytest.approx(
        configured, abs=0.02
    )
    # the three fractions are reported separately because they genuinely differ
    assert manifest["realized_attack_actor_fraction"] < configured
    assert manifest["realized_attack_request_fraction"] > configured


def test_long_horizon_families_are_not_truncated(bundle):
    """`actor_start_window_days` bounds starts, not the benchmark's span."""
    window = bundle["manifest"]["window"]
    days = window["actor_start_window_days"]
    assert window["realized_event_span_days"] > days
    last_start = datetime.fromisoformat(window["last_actor_start"])
    first_start = datetime.fromisoformat(window["first_actor_start"])
    assert (last_start - first_start).total_seconds() / 86400 <= days


def test_merchant_kind_is_not_a_model_feature():
    """Unseen merchants must test behavioural generalisation, not a missing
    categorical lookup."""
    assert "merchant_kind" not in MODEL_FEATURES
    assert not any("merchant" in name for name in MODEL_FEATURES)


# --- lifecycle and schema ---------------------------------------------------


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


def test_labels_stay_outside_the_engine(bundle, features):
    """Labels are joined after replay, never fed to the FeatureEngine."""
    assert features.label.notna().all()
    assert set(features.label) <= {0, 1}
    assert "merchant_origin" in bundle["labels"].columns


def test_all_twenty_families_produce_devices(bundle, small_config):
    assert set(bundle["labels"].scenario) == set(small_config["scenarios"])


def test_blind_only_mechanics_actually_fire(bundle, features):
    """`dormant_gap_days` and `burst_pause` are the mechanics the development
    generator does not have -- they must show up in the data."""
    labels = bundle["labels"][["device_id", "scenario"]].drop_duplicates("device_id")
    tagged = features.merge(labels, on="device_id", how="left", suffixes=("", "_lab"))

    dormant = tagged.loc[tagged.scenario_lab.eq("dormant_returning_customer")]
    assert len(dormant) > 0
    # a dormant device carries real age with no recent activity
    assert dormant.device_age_seconds.max() > 30 * 86400

    burst = tagged.loc[tagged.scenario_lab.eq("burst_pause_burst")]
    assert len(burst) > 0
    assert burst.seconds_since_last_request.max() > 3600


# --- determinism and guards -------------------------------------------------


def test_generation_is_deterministic(small_config):
    first = generate_blind_bundle(small_config, SPEC, DEV_MANIFEST)
    second = generate_blind_bundle(small_config, SPEC, DEV_MANIFEST)
    pd.testing.assert_frame_equal(first["raw_events"], second["raw_events"])
    pd.testing.assert_frame_equal(first["labels"], second["labels"])
    assert (
        first["manifest"]["blind_config_sha256"]
        == second["manifest"]["blind_config_sha256"]
    )


def test_a_changed_seed_changes_the_benchmark(small_config):
    changed = copy.deepcopy(small_config)
    changed["seed"] += 1
    baseline = generate_blind_bundle(small_config, SPEC, DEV_MANIFEST)["raw_events"]
    shifted = generate_blind_bundle(changed, SPEC, DEV_MANIFEST)["raw_events"]
    assert not baseline.equals(shifted)


def test_the_manifest_records_provenance_and_no_metrics(bundle):
    manifest = bundle["manifest"]
    assert manifest["blind_version"] == "v1.1"
    assert manifest["blind_evaluated"] is False
    assert manifest["contains_model_metrics"] is False
    assert manifest["contains_policy_metrics"] is False
    for key in (
        "blind_config_sha256",
        "blind_spec_sha256",
        "feature_contract_sha256",
        "seed",
        "devices",
        "requests",
        "merchants",
        "scenario_devices",
        "merchant_kind_devices",
        "merchant_origin_counts",
        "window",
        "configured_attack_device_fraction",
        "realized_attack_device_fraction",
        "realized_attack_request_fraction",
        "realized_attack_actor_fraction",
        "configured_merchant_kinds",
        "realized_merchant_kinds",
        "merchant_instances_per_kind",
        "merchant_kind_requests",
    ):
        assert key in manifest, key
    # No metric may appear as a KEY or a numeric value. (The prose
    # disclosure legitimately mentions recall and precision to explain why
    # they must be read carefully -- that is documentation, not a result.)
    metric_words = (
        "recall",
        "precision",
        "risk_score",
        "pr_auc",
        "roc_auc",
        "brier",
        "fpr",
        "block_rate",
        "review_rate",
    )

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                assert not any(
                    word in key.lower() for word in metric_words
                ), f"metric-shaped key at {path}.{key}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(manifest)


def test_a_consumed_benchmark_cannot_be_regenerated(tmp_path):
    """Once results are observed the benchmark is spent; regenerating would
    silently give the system a second look at a held-out set."""
    manifest = tmp_path / "freeze.json"
    manifest.write_text(json.dumps({"blind_version": "v1", "consumed": True}))
    with pytest.raises(BlindBenchmarkError, match="consumed"):
        assert_not_consumed(manifest)

    manifest.write_text(
        json.dumps({"blind_version": "v1", "consumed": False, "blind_evaluated": True})
    )
    with pytest.raises(BlindBenchmarkError, match="consumed"):
        assert_not_consumed(manifest)


def test_generation_requires_a_freeze_record(tmp_path):
    with pytest.raises(BlindBenchmarkError, match="freeze manifest is missing"):
        assert_not_consumed(tmp_path / "absent.json")


def test_the_live_benchmark_can_no_longer_be_regenerated():
    """Blind v1.1 has been evaluated, so regeneration is refused outright."""
    with pytest.raises(BlindBenchmarkError, match="consumed"):
        assert_not_consumed(ROOT / "artifacts/evaluation/blind_freeze_manifest.json")


# --- shift report -----------------------------------------------------------


def test_the_shift_report_uses_features_only(features):
    development = pd.read_csv(ROOT / "data/generated/development/features.csv")
    report = shift_report(development.loc[development.split.eq("validation")], features)
    assert set(report.feature) == set(MODEL_FEATURES)
    assert set(report.columns) == {
        "feature",
        "development_median",
        "blind_median",
        "development_p90",
        "blind_p90",
        "psi",
        "ks",
        "overlap_coefficient",
    }
    assert (report.psi >= 0).all()
    assert report.ks.between(0, 1).all()


def test_only_the_version_stamped_result_file_exists():
    """Results live in a version-stamped file, never a mutable generic name.
    v1.0 was never evaluated, so no v1 metrics file exists either."""
    evaluation = ROOT / "artifacts/evaluation"
    assert (evaluation / "blind_metrics_v1_1.json").is_file()
    for name in ("blind_metrics_v1.json", "blind_metrics.json"):
        assert not (evaluation / name).exists()
