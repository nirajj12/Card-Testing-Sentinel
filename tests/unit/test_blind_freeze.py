"""The freeze record must actually pin the frozen system.

These are the tests that make "frozen" mean something: if the model, the
policy, the feature contract or the blind specification changes after the
freeze, verification has to fail rather than quietly carry on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "artifacts/evaluation/blind_freeze_manifest.json"
SPEC = ROOT / "docs/blind_spec.md"
BLIND_CONFIG = ROOT / "configs/blind.yaml"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- the freeze exists and is honest ----------------------------------------


def test_the_freeze_manifest_records_the_one_time_evaluation(manifest):
    """Blind v1.1 has been evaluated exactly once and is now spent."""
    assert manifest["blind_version"] == "v1.1"
    assert manifest["blind_evaluated"] is True
    assert manifest["consumed"] is True
    # consumption is stamped before the metrics are written, never after
    assert manifest["evaluation_started_utc"] <= manifest["evaluation_completed_utc"]
    assert manifest["blind_metrics_file"] == "blind_metrics_v1_1.json"


def test_every_frozen_development_dependency_is_recorded(manifest):
    development = manifest["development"]
    for key in (
        "model_sha256",
        "model_metadata_sha256",
        "feature_contract_sha256",
        "policy_sha256",
        "training_config_sha256",
        "policy_config_sha256",
        "development_manifest_sha256",
    ):
        assert key in development, key
        assert len(development[key]) == 64


def test_the_frozen_model_on_disk_still_matches_the_freeze(manifest):
    development = manifest["development"]
    for key, name in development["files"].items():
        assert sha256(ROOT / name) == development[key], f"{name} changed since freeze"


def test_the_frozen_policy_binds_the_frozen_model(manifest):
    policy = json.loads((ROOT / "artifacts/policy/operational_policy.json").read_text())
    assert policy["model_sha256"] == manifest["development"]["model_sha256"]
    assert policy["blind_evaluated"] is False


def test_the_feature_contract_hash_agrees_with_the_running_code(manifest):
    from card_testing_sentinel.features.specification import MODEL_FEATURES_SHA256

    contract = json.loads((ROOT / "artifacts/model/feature_contract.json").read_text())
    assert contract["feature_contract_sha256"] == MODEL_FEATURES_SHA256


def test_verification_detects_drift(tmp_path, monkeypatch):
    """A changed frozen file must be caught, not shrugged off."""
    import scripts.freeze_blind_benchmark as freeze

    drift = freeze.verify()
    assert drift == [], f"unexpected drift before tampering: {drift}"

    original = freeze.sha256_file

    def tampered(path):
        if path.name == "risk_model.joblib":
            return "0" * 64
        return original(path)

    monkeypatch.setattr(freeze, "sha256_file", tampered)
    assert any("risk_model.joblib" in problem for problem in freeze.verify())


# --- the blind side of the freeze -------------------------------------------


def test_the_blind_spec_and_config_are_frozen(manifest):
    blind = manifest["blind"]
    assert blind["blind_spec_sha256"] == sha256(SPEC)
    assert blind["blind_config_sha256"] == sha256(BLIND_CONFIG)
    assert len(blind["blind_generator_sha256"]) == 64


def test_the_generator_source_bundle_is_frozen(manifest):
    import scripts.freeze_blind_benchmark as freeze

    blind = manifest["blind"]
    actual = freeze.bundle_hash(tuple(blind["blind_generator_sources"]))
    assert actual == blind["blind_generator_sha256"]


def test_the_spec_was_written_before_the_generator_was_frozen(manifest):
    """Stage ordering: development pinned first, blind pinned after."""
    assert manifest["development"]["frozen_utc"] <= manifest["blind"]["frozen_utc"]


def test_the_superseded_revision_is_preserved_not_erased(manifest):
    """v1.0 existed and failed pre-evaluation validation. Hiding that would
    hide how many times the specification was touched."""
    history = manifest["revision_history"]
    v1 = next(entry for entry in history if entry["blind_version"] == "v1")
    assert v1["blind_evaluated"] is False
    assert v1["consumed"] is False
    assert v1["blind"]["blind_spec_sha256"] != manifest["blind"]["blind_spec_sha256"]
    assert "FAILED its own pre-evaluation validation" in v1["reason"]
    assert "NO model score" in v1["reason"]


def test_the_generator_bundle_covers_the_whole_generation_path(manifest):
    """v1.0's defect lived in merchants.py, which the bundle did not hash."""
    sources = set(manifest["blind"]["blind_generator_sources"])
    for name in (
        "src/card_testing_sentinel/ml/blind_generator.py",
        "src/card_testing_sentinel/ml/merchants.py",
        "src/card_testing_sentinel/ml/scenarios.py",
        "src/card_testing_sentinel/ml/primitives.py",
    ):
        assert name in sources, name


def test_the_generated_benchmark_itself_is_frozen(manifest):
    """After validation the dataset is immutable: a silent regeneration with
    different bytes must fail verification."""
    dataset = manifest["dataset"]
    for key, name in dataset["files"].items():
        assert sha256(ROOT / name) == dataset[key], f"{name} changed since the freeze"
    assert dataset["frozen_utc"] >= manifest["blind"]["frozen_utc"]


def test_the_spec_records_the_v1_failure_and_that_nothing_was_observed():
    # strip markdown blockquote markers and wrapping before matching prose
    raw = SPEC.read_text().replace("**", "")
    text = " ".join(line.lstrip("> ") for line in raw.splitlines())
    text = " ".join(text.split())
    assert "pre-evaluation validation FAILED" in text
    assert "No model score, policy decision, recall, precision, PR-AUC, FPR" in text
    assert "v1.0 was never evaluated and was never consumed" in text


# --- the specification says what it must ------------------------------------


def test_the_spec_declares_its_version_and_the_consumed_rule():
    text = SPEC.read_text()
    assert "# Blind Benchmark Specification — v1.1" in text
    assert "No blind performance number has been observed" in text
    for required in (
        "consumed",
        "blind_metrics_v1.json",
        "blind_version: v2",
        "new seed",
    ):
        assert required in text, required


def test_the_spec_pre_registers_the_evaluation_metrics():
    # collapse wrapping so a line break inside a metric name is not a miss
    text = " ".join(SPEC.read_text().split())
    for metric in (
        "PR-AUC",
        "ROC-AUC",
        "Brier",
        "log loss",
        "ECE",
        "attack review-or-higher recall",
        "attack block recall",
        "legitimate review-or-higher rate",
        "legitimate block rate",
        "median and p90 first review attempt",
        "never detected",
    ):
        assert metric in text, metric


def test_the_spec_sets_no_pass_mark():
    """A target number would create pressure to reach it."""
    text = SPEC.read_text()
    assert "no pass mark" in text.lower()
    assert "There is **no pass mark.**" in text


# --- the config is genuinely its own ----------------------------------------


@pytest.fixture(scope="module")
def blind_config() -> dict:
    return yaml.safe_load(BLIND_CONFIG.read_text())


@pytest.fixture(scope="module")
def training_config() -> dict:
    return yaml.safe_load((ROOT / "configs/training.yaml").read_text())


def test_the_blind_seed_is_unrelated_to_every_development_seed(
    blind_config, training_config
):
    development_seeds = {
        int(training_config["splits"]["train"]["seed"]),
        int(training_config["splits"]["validation"]["seed"]),
        int(training_config["merchants"]["seed"]),
        int(training_config["training"]["seed"]),
    }
    assert int(blind_config["seed"]) not in development_seeds
    assert int(blind_config["merchants"]["seed"]) not in development_seeds


def test_the_blind_config_is_not_a_copy_of_training(blind_config, training_config):
    """Different scenario families, not the same table with a new seed."""
    assert set(blind_config["scenarios"]) != set(training_config["scenarios"])
    assert not set(blind_config["scenarios"]) & set(training_config["scenarios"])


def test_the_blind_window_opens_after_development(blind_config, training_config):
    from datetime import datetime

    development = json.loads(
        (ROOT / "data/generated/development/manifest.json").read_text()
    )
    last = max(
        datetime.fromisoformat(split["last_event"])
        for split in development["splits"].values()
    )
    start = blind_config["window"]["start"]
    start = start if isinstance(start, datetime) else datetime.fromisoformat(str(start))
    assert start > last


def test_no_policy_threshold_leaks_into_the_blind_config():
    """The benchmark must not be designed around the system's operating point."""
    policy = yaml.safe_load((ROOT / "configs/policy.yaml").read_text())["policy"]
    blind = yaml.safe_load(BLIND_CONFIG.read_text())

    def keys(node):
        """Every mapping key anywhere in the config."""
        if isinstance(node, dict):
            for key, value in node.items():
                yield str(key)
                yield from keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from keys(item)

    blind_keys = set(keys(blind))
    for key in (
        "review_threshold",
        "block_threshold",
        "block_evidence",
        "block_elevated_count",
        "review_risk_score",
        "block_risk_score",
    ):
        assert key not in blind_keys, f"policy key '{key}' appears in the blind config"

    # Deliberately NOT asserting that the threshold *values* are absent: the
    # blind config is full of probabilities, so 0.60 appearing as the end of a
    # `method_validity` range is a coincidence, not leakage. The meaningful
    # guarantee is structural -- the generator cannot import the policy at all
    # (see test_the_generator_never_reaches_the_model_or_the_policy), and no
    # policy key appears here.
    assert "policy" not in blind_keys
    assert policy["family"] not in blind_keys


def test_the_blind_population_declares_ten_families_per_side(blind_config):
    scenarios = blind_config["scenarios"]
    legitimate = [n for n, s in scenarios.items() if s["population"] == "legitimate"]
    attack = [n for n, s in scenarios.items() if s["population"] == "attack"]
    assert len(legitimate) == 10
    assert len(attack) == 10


def test_the_blind_config_declares_unseen_merchant_kinds(blind_config, training_config):
    kinds = blind_config["merchants"]["kinds"]
    unseen = {n for n, s in kinds.items() if s.get("origin") == "unseen"}
    known = {n for n, s in kinds.items() if s.get("origin", "known") == "known"}
    assert len(unseen) >= 2
    assert not unseen & set(training_config["merchants"]["kinds"])
    assert known <= set(training_config["merchants"]["kinds"])


def test_the_attack_fraction_is_labelled_a_sampling_choice(blind_config):
    text = BLIND_CONFIG.read_text()
    fraction = blind_config["population"]["benchmark_attack_device_fraction"]
    assert 0.05 <= fraction <= 0.35
    assert "SAMPLING CHOICE" in text
    assert "not an estimate" in text
