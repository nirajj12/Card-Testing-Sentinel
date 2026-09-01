"""Dataset V2 generator: reproducibility, causality and scenario coverage.

These run on a small config so they stay fast; the shape of the checks is
independent of the row count.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from card_testing_sentinel.ml.generator import (
    EVENT_COLUMNS,
    config_hash,
    generate_development_dataset,
    load_config,
)
from card_testing_sentinel.ml.scenarios import draw_behavior, load_scenarios
from card_testing_sentinel.ml.validation import OUTCOME_ONLY_FIELDS

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config() -> dict:
    return load_config(ROOT / "configs/training.yaml")


@pytest.fixture(scope="module")
def small_config(config) -> dict:
    small = copy.deepcopy(config)
    small["splits"]["train"]["devices"] = 260
    small["splits"]["validation"]["devices"] = 120
    return small


@pytest.fixture(scope="module")
def bundle(small_config) -> dict:
    return generate_development_dataset(small_config)


def test_same_seed_and_config_reproduce_the_dataset_exactly(small_config):
    first = generate_development_dataset(small_config)
    second = generate_development_dataset(small_config)
    pd.testing.assert_frame_equal(first["raw_events"], second["raw_events"])
    pd.testing.assert_frame_equal(first["labels"], second["labels"])
    pd.testing.assert_frame_equal(
        first["split_assignments"], second["split_assignments"]
    )
    assert first["manifest"]["config_sha256"] == second["manifest"]["config_sha256"]


def test_a_changed_config_changes_the_hash_and_the_data(small_config):
    changed = copy.deepcopy(small_config)
    changed["splits"]["train"]["seed"] += 1
    assert config_hash(changed) != config_hash(small_config)
    baseline = generate_development_dataset(small_config)["raw_events"]
    shifted = generate_development_dataset(changed)["raw_events"]
    assert not baseline.equals(shifted)


def test_generator_emits_raw_lifecycle_events_not_feature_rows(bundle):
    raw = bundle["raw_events"]
    assert set(EVENT_COLUMNS) <= set(raw.columns)
    assert set(raw.event_type) <= {
        "authorization_request",
        "authorization_outcome",
        "checkout_completion",
    }
    from card_testing_sentinel.features.specification import MODEL_FEATURES

    assert not set(MODEL_FEATURES) & set(
        raw.columns
    ), "the generator must never emit a model feature"


def test_request_events_never_carry_outcome_or_card_metadata(bundle):
    requests = bundle["raw_events"].pipe(
        lambda frame: frame.loc[frame.event_type.eq("authorization_request")]
    )
    for field in OUTCOME_ONLY_FIELDS:
        assert requests[field].isna().all(), field
    assert requests.merchant_id.notna().all()
    assert (requests.amount > 0).all()


def test_card_metadata_appears_only_on_card_outcomes(bundle):
    outcomes = bundle["raw_events"].pipe(
        lambda frame: frame.loc[frame.event_type.eq("authorization_outcome")]
    )
    card = outcomes.loc[outcomes.payment_method.eq("card")]
    other = outcomes.loc[~outcomes.payment_method.eq("card")]
    assert card.card_last4.notna().all()
    assert other.card_last4.isna().all(), "only card payments report a last4"
    # last4 must collide: it is a weak hint, never an identity
    assert card.card_last4.nunique() < len(card)


def test_labels_and_scenarios_never_reach_the_event_stream(bundle):
    raw = bundle["raw_events"]
    encoded = raw.to_csv(index=False)
    for scenario in load_scenarios(load_config(ROOT / "configs/training.yaml")):
        assert scenario not in encoded
    for forbidden in ("label", "population", "attack", "legitimate", "scenario"):
        assert forbidden not in set(raw.columns)


def test_every_configured_scenario_produces_devices(bundle, config):
    produced = set(bundle["labels"].scenario)
    assert produced == set(config["scenarios"])


def test_both_populations_and_all_merchant_kinds_are_represented(bundle, config):
    labels = bundle["labels"]
    assert set(labels.population) == {"legitimate", "attack"}
    assert labels.label.isin({0, 1}).all()
    assert labels.merchant_id.nunique() <= int(config["merchants"]["count"])
    assert labels.merchant_kind.nunique() >= 4


def test_attackers_and_legitimate_actors_share_merchants(bundle):
    """Merchant kind must not imply the label -- attackers target ordinary
    merchants, so the two populations have to overlap on merchants."""
    labels = bundle["labels"]
    attacked = set(labels.loc[labels.label.eq(1)].merchant_id)
    legitimate = set(labels.loc[labels.label.eq(0)].merchant_id)
    assert len(attacked & legitimate) >= 5


def test_train_and_validation_are_separated_by_device_seed_and_time(bundle):
    labels = bundle["labels"]
    train = set(labels.loc[labels.split.eq("train")].device_id)
    validation = set(labels.loc[labels.split.eq("validation")].device_id)
    assert train and validation
    assert not (train & validation)

    raw = bundle["raw_events"].assign(
        ts=lambda frame: pd.to_datetime(frame.timestamp, format="ISO8601")
    )
    windows = raw.groupby("split").ts.agg(["min", "max"])
    assert windows.loc["validation", "min"] > windows.loc["train", "min"]
    for column in ("event_id", "request_id", "session_id", "ip_fingerprint"):
        assert not (
            set(raw.loc[raw.split.eq("train"), column].dropna())
            & set(raw.loc[raw.split.eq("validation"), column].dropna())
        )


def test_shared_merchants_survive_the_split(bundle):
    labels = bundle["labels"]
    train = set(labels.loc[labels.split.eq("train")].merchant_id)
    validation = set(labels.loc[labels.split.eq("validation")].merchant_id)
    assert validation <= train, "validation must reuse the training merchants"


def test_manifest_records_provenance_but_no_model(bundle):
    manifest = bundle["manifest"]
    assert manifest["model_trained"] is False
    assert not any("model_sha" in key for key in manifest)
    for key in (
        "config_sha256",
        "feature_contract_sha256",
        "seeds",
        "events",
        "requests",
        "devices",
        "merchants",
        "scenario_devices",
    ):
        assert key in manifest


def test_behavior_draws_stay_inside_the_declared_scenario_ranges(config):
    import numpy as np

    rng = np.random.default_rng(11)
    for scenario in load_scenarios(config).values():
        for _ in range(25):
            behavior = draw_behavior(rng, scenario)
            assert scenario.attempts[0] <= behavior.attempts <= scenario.attempts[1]
            assert (
                scenario.method_validity[0]
                <= behavior.method_validity
                <= scenario.method_validity[1]
            )
            assert (
                scenario.gap_seconds[0]
                <= behavior.gap_seconds
                <= scenario.gap_seconds[1]
            )


def test_latent_parameter_ranges_overlap_across_populations(config):
    """The anti-shortcut guarantee, asserted on the config itself: for the
    parameters that drive the strongest observables, at least one legitimate
    and one attack scenario must share overlapping ranges."""
    scenarios = load_scenarios(config).values()
    legitimate = [s for s in scenarios if s.population == "legitimate"]
    attack = [s for s in scenarios if s.population == "attack"]

    def overlaps(left, right) -> bool:
        return left[0] <= right[1] and right[0] <= left[1]

    for field in ("method_validity", "gap_seconds", "session_rotation", "ip_rotation"):
        pairs = [
            (a.name, b.name)
            for a in legitimate
            for b in attack
            if overlaps(getattr(a, field), getattr(b, field))
        ]
        assert pairs, f"no legitimate/attack overlap on {field}"


# --- Phase 3B: campaigns and benchmark prevalence ---------------------------


def test_campaign_windows_belong_to_the_merchant_calendar(config):
    """Campaigns are a deterministic merchant/time schedule, not a per-actor
    coin flip, so flash-sale shoppers and camouflaged attackers share one
    context."""
    import numpy as np

    from card_testing_sentinel.ml.merchants import build_merchants

    merchants = build_merchants(
        np.random.default_rng(int(config["merchants"]["seed"])), config["merchants"]
    )
    by_kind = {}
    for merchant in merchants:
        by_kind.setdefault(merchant.kind, []).append(merchant)
        for opens, closes in merchant.campaign_windows:
            assert closes > opens

    # a flash-sale merchant runs sales far more of the time than a
    # subscription merchant, which is a business fact, not a risk signal
    if "flash_sale" in by_kind and "subscription" in by_kind:
        flash = max(m.campaign_share for m in by_kind["flash_sale"])
        subscription = max(m.campaign_share for m in by_kind["subscription"])
        assert flash > subscription


def test_campaign_membership_is_a_pure_function_of_time(config):
    import numpy as np

    from card_testing_sentinel.ml.merchants import build_merchants

    merchants = build_merchants(
        np.random.default_rng(int(config["merchants"]["seed"])), config["merchants"]
    )
    merchant = next(m for m in merchants if m.campaign_windows)
    opens, closes = merchant.campaign_windows[0]
    midpoint = opens + (closes - opens) / 2
    assert merchant.in_campaign(midpoint)
    assert not merchant.in_campaign(opens - timedelta(days=30))


def test_manifest_names_the_benchmark_prevalence_and_disclaims_it(bundle):
    manifest = bundle["manifest"]
    assert "prevalence_disclosure" in manifest
    disclosure = manifest["prevalence_disclosure"].lower()
    assert "not an estimate" in disclosure
    assert "production precision" in disclosure
    for split in manifest["splits"].values():
        # the key must not read like a production estimate
        assert "benchmark_attack_fraction" in split
        assert "attack_fraction" not in {
            key for key in split if key != "benchmark_attack_fraction"
        }


def test_manifest_records_resolved_windows_and_scenario_profile(bundle):
    manifest = bundle["manifest"]
    train = manifest["splits"]["train"]
    validation = manifest["splits"]["validation"]
    assert train["last_event"] < validation["first_event"]
    profile = manifest["scenario_profile"]
    assert set(profile) == set(bundle["labels"].scenario.unique())
    assert all(row["requests"] > 0 for row in profile.values())


def test_labels_retain_the_grouping_needed_for_prevalence_free_metrics(bundle):
    """Per-scenario recall and per-scenario false-positive rate are far less
    sensitive to the synthetic class balance than aggregate precision, so the
    grouping columns must survive into the tables."""
    for column in (
        "device_id",
        "scenario",
        "population",
        "label",
        "merchant_kind",
        "split",
    ):
        assert column in bundle["labels"].columns
