"""Baseline comparison: deterministic computation and frozen-artifact contract.

The comparison functions are exercised against a small hand-built frame rather
than the real blind rows, because `conftest.forbid_protected_blind_row_reads`
deliberately fails any test that opens `blind_event_decisions.csv`. That guard
is the point -- the rows are build-time input only -- so these tests validate
the *committed artifact* and the *pure computation*, never the two together.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from card_testing_sentinel.common.integrity import sha256_file

ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    """Import the build-time script by path.

    `scripts/` is deliberately not a package -- these are operator entry
    points, not shipped library code -- so it is loaded explicitly rather
    than by adding an __init__.py just to satisfy a test.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "baseline_comparison_script", ROOT / "scripts/baseline_comparison.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_generator = _load_generator()
SCHEMA_VERSION = _generator.SCHEMA_VERSION
ContractError = _generator.ContractError
build_artifact = _generator.build_artifact
build_baselines = _generator.build_baselines
evaluate_dominance = _generator.evaluate_dominance
load_devices = _generator.load_devices
ARTIFACT = ROOT / "artifacts/evaluation/baseline_comparison.json"
MANIFEST = ROOT / "artifacts/release_manifest.json"


@pytest.fixture(scope="module")
def artifact() -> dict:
    return json.loads(ARTIFACT.read_text())


def _frame(rows: list[dict]) -> pd.DataFrame:
    """Build the collapsed per-device frame the comparison operates on."""
    return pd.DataFrame(rows).set_index("device_id")


# ── pure computation ────────────────────────────────────────────────────


def test_recall_and_false_positive_rate_use_device_denominators():
    devices = _frame(
        [
            {
                "device_id": "a1",
                "requests": 9,
                "max_rule_score": 6,
                "intervened": True,
                "is_attack": True,
            },
            {
                "device_id": "a2",
                "requests": 4,
                "max_rule_score": 1,
                "intervened": False,
                "is_attack": True,
            },
            {
                "device_id": "l1",
                "requests": 1,
                "max_rule_score": 0,
                "intervened": False,
                "is_attack": False,
            },
            {
                "device_id": "l2",
                "requests": 6,
                "max_rule_score": 3,
                "intervened": True,
                "is_attack": False,
            },
        ]
    )
    rows = {row["id"]: row for row in build_baselines(devices)}
    count5 = rows["count_ge_5"]
    assert count5["attacker_detected"] == 1 and count5["attacker_devices"] == 2
    assert count5["attacker_recall"] == 0.5
    assert count5["legitimate_flagged"] == 1 and count5["legitimate_devices"] == 2
    assert count5["legitimate_false_positive_rate"] == 0.5

    sentinel = rows["sentinel_review_or_higher"]
    assert sentinel["is_sentinel"] is True
    assert sentinel["attacker_recall"] == 0.5
    assert sentinel["legitimate_false_positive_rate"] == 0.5


def test_computation_is_deterministic_across_repeated_calls():
    devices = _frame(
        [
            {
                "device_id": f"a{i}",
                "requests": 5 + i,
                "max_rule_score": 4,
                "intervened": True,
                "is_attack": True,
            }
            for i in range(6)
        ]
        + [
            {
                "device_id": f"l{i}",
                "requests": 1,
                "max_rule_score": 0,
                "intervened": False,
                "is_attack": False,
            }
            for i in range(6)
        ]
    )
    assert build_baselines(devices) == build_baselines(devices)


def test_dominance_is_computed_not_asserted():
    """A baseline that genuinely beats Sentinel on both axes must flip the
    verdict, so the UI can never keep rendering a stale claim."""
    beaten = [
        {
            "id": "count_ge_5",
            "attacker_recall": 0.99,
            "legitimate_false_positive_rate": 0.001,
        },
        {
            "id": "sentinel_review_or_higher",
            "is_sentinel": True,
            "attacker_recall": 0.90,
            "legitimate_false_positive_rate": 0.01,
        },
    ]
    verdict = evaluate_dominance(beaten)
    assert verdict["dominated"] is True
    assert verdict["dominating_baselines"] == ["count_ge_5"]
    assert "statement" not in verdict


def test_a_baseline_better_on_only_one_axis_does_not_dominate():
    mixed = [
        {
            "id": "count_ge_5",
            "attacker_recall": 0.99,
            "legitimate_false_positive_rate": 0.05,
        },
        {
            "id": "count_ge_10",
            "attacker_recall": 0.30,
            "legitimate_false_positive_rate": 0.0,
        },
        {
            "id": "sentinel_review_or_higher",
            "is_sentinel": True,
            "attacker_recall": 0.90,
            "legitimate_false_positive_rate": 0.01,
        },
    ]
    verdict = evaluate_dominance(mixed)
    assert verdict["dominated"] is False
    assert "beats Sentinel on" in verdict["statement"]


# ── loader contract: fails loudly, never silently ───────────────────────


def test_missing_file_raises(tmp_path):
    with pytest.raises(ContractError, match="missing"):
        load_devices(tmp_path / "absent.csv")


def test_missing_columns_raise(tmp_path):
    path = tmp_path / "decisions.csv"
    pd.DataFrame({"device_id": ["a"], "action": ["allow"]}).to_csv(path, index=False)
    with pytest.raises(ContractError, match="missing columns"):
        load_devices(path)


def test_uncontracted_action_raises(tmp_path):
    path = tmp_path / "decisions.csv"
    pd.DataFrame(
        {
            "device_id": ["a", "b"],
            "request_index": [1, 1],
            "action": ["allow", "quarantine"],
            "rule_score": [0, 0],
            "scenario_tag": ["attack_burst", "normal_standard"],
        }
    ).to_csv(path, index=False)
    with pytest.raises(ContractError, match="uncontracted actions"):
        load_devices(path)


def test_single_population_raises(tmp_path):
    path = tmp_path / "decisions.csv"
    pd.DataFrame(
        {
            "device_id": ["a", "b"],
            "request_index": [1, 1],
            "action": ["allow", "allow"],
            "rule_score": [0, 0],
            "scenario_tag": ["normal_standard", "normal_standard"],
        }
    ).to_csv(path, index=False)
    with pytest.raises(ContractError, match="both populations"):
        load_devices(path)


def test_loader_round_trips_into_a_complete_artifact(tmp_path):
    path = tmp_path / "decisions.csv"
    rows = []
    for index in range(4):
        rows += [
            {
                "device_id": f"a{index}",
                "request_index": step + 1,
                "action": "block" if step > 5 else "allow",
                "rule_score": 6,
                "scenario_tag": "attack_burst",
            }
            for step in range(8)
        ]
    for index in range(4):
        rows.append(
            {
                "device_id": f"l{index}",
                "request_index": 1,
                "action": "allow",
                "rule_score": 0,
                "scenario_tag": "normal_standard",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
    devices = load_devices(path)
    assert len(devices) == 8
    built = build_artifact(devices)
    assert built["schema_version"] == SCHEMA_VERSION
    assert {row["id"] for row in built["baselines"]} == {
        "count_ge_4",
        "count_ge_5",
        "count_ge_7",
        "count_ge_10",
        "rules_ge_3",
        "rules_ge_5",
        "sentinel_review_or_higher",
    }


# ── the committed frozen artifact ───────────────────────────────────────


def test_artifact_exists_and_declares_the_supported_schema(artifact):
    assert artifact["schema_version"] == SCHEMA_VERSION
    assert artifact["source"]["attacker_devices"] == 300
    assert artifact["source"]["legitimate_devices"] == 1700
    assert artifact["source"]["devices"] == 2000


def test_artifact_covers_every_required_approach(artifact):
    identifiers = [row["id"] for row in artifact["baselines"]]
    for required in (
        "count_ge_5",
        "count_ge_7",
        "count_ge_10",
        "rules_ge_3",
        "rules_ge_5",
    ):
        assert required in identifiers
    sentinel = [row for row in artifact["baselines"] if row.get("is_sentinel")]
    assert len(sentinel) == 1


def test_every_rate_is_consistent_with_its_own_numerator_and_denominator(artifact):
    """Rates are stored alongside their counts, so they must agree. A mismatch
    would mean the artifact was edited by hand rather than generated."""
    for row in artifact["baselines"]:
        assert row["attacker_recall"] == pytest.approx(
            row["attacker_detected"] / row["attacker_devices"]
        )
        assert row["legitimate_false_positive_rate"] == pytest.approx(
            row["legitimate_flagged"] / row["legitimate_devices"]
        )
        assert 0 <= row["attacker_recall"] <= 1
        assert 0 <= row["legitimate_false_positive_rate"] <= 1


def test_every_approach_shares_the_same_denominators(artifact):
    """A comparison across different denominators would be meaningless."""
    assert {row["attacker_devices"] for row in artifact["baselines"]} == {300}
    assert {row["legitimate_devices"] for row in artifact["baselines"]} == {1700}


def test_higher_count_thresholds_never_increase_recall(artifact):
    counts = sorted(
        (row for row in artifact["baselines"] if row["family"] == "request_count"),
        key=lambda row: row["threshold"],
    )
    recalls = [row["attacker_recall"] for row in counts]
    false_positives = [row["legitimate_false_positive_rate"] for row in counts]
    assert recalls == sorted(recalls, reverse=True)
    assert false_positives == sorted(false_positives, reverse=True)


def test_sentinel_row_matches_the_frozen_blind_metrics(registry):
    """Cross-check: the Sentinel row is recomputed from the decision rows,
    while blind_metrics was written by the evaluation run. They must agree,
    or one of the two artifacts is stale."""
    artifact = json.loads(ARTIFACT.read_text())
    sentinel = next(row for row in artifact["baselines"] if row.get("is_sentinel"))
    policy = registry.blind_metrics["operational_policy"]
    assert (
        sentinel["attacker_detected"]
        == policy["attacker_review_or_higher"]["numerator"]
    )
    assert sentinel["legitimate_flagged"] == policy["legitimate_review_or_higher"]


def test_dominance_verdict_is_present_and_self_consistent(artifact):
    dominance = artifact["dominance"]
    sentinel = next(row for row in artifact["baselines"] if row.get("is_sentinel"))
    recomputed = evaluate_dominance(artifact["baselines"])
    assert dominance["dominated"] == recomputed["dominated"]
    assert dominance["dominating_baselines"] == recomputed["dominating_baselines"]
    if dominance["dominated"]:
        assert "statement" not in dominance
    else:
        assert "beats Sentinel on" in dominance["statement"]
        for row in artifact["baselines"]:
            if row.get("is_sentinel"):
                continue
            better_recall = row["attacker_recall"] >= sentinel["attacker_recall"]
            better_cost = (
                row["legitimate_false_positive_rate"]
                <= sentinel["legitimate_false_positive_rate"]
            )
            assert not (better_recall and better_cost)


# ── manifest registration ───────────────────────────────────────────────


def test_artifact_is_registered_in_the_release_manifest():
    manifest = json.loads(MANIFEST.read_text())
    entry = manifest["artifacts"]["baseline_comparison"]
    assert entry["path"] == "artifacts/evaluation/baseline_comparison.json"
    assert entry["sha256"] == sha256_file(ARTIFACT)


def test_recorded_manifest_checksum_matches_the_manifest_file():
    recorded = (ROOT / "artifacts/release_manifest.sha256").read_text().split()[0]
    assert recorded == sha256_file(MANIFEST)


def test_adding_the_baseline_entry_left_every_protected_hash_untouched():
    """Model, calibrator, feature contract, policy and blind-evaluation hashes
    must be byte-identical to what the frozen release already declared."""
    manifest = json.loads(MANIFEST.read_text())
    model_sha = "6c638fc05ca321e98c8b5417c477a58e2649bdd7e056bcd56e0d119d3eb80f88"
    expected = {
        "model": model_sha,
        "calibrator": model_sha,
        "policy": ("9afeba2df176c87287e86ff0402ef96b58e9386608d003b5702986be02b6ae95"),
        "blind_metrics": (
            "5fba17e8a8458c290934dece38ef70ef28d5b6eed93709ba9b8f3950a3130ef6"
        ),
        "blind_event_decisions": (
            "e6e6b2481c09edb44c1782165b97c5c59864890fd03ddbfdb991b1ec41605817"
        ),
        "blind_device_summary": (
            "b5c6a7ff1e925dfeff66d815b39bcc9716be06239e4d1276e931fd798c7f1a55"
        ),
    }
    for name, digest in expected.items():
        assert manifest["artifacts"][name]["sha256"] == digest, name


def test_the_lowest_threshold_anchors_the_trade_off(artifact):
    """Count >=4 catches every attacker and disrupts the most legitimate
    customers. It is the point that makes the trade-off legible, so it must
    be present and must sit at the extreme of both axes."""
    counts = [row for row in artifact["baselines"] if row["family"] == "request_count"]
    lowest = min(counts, key=lambda row: row["threshold"])
    assert lowest["threshold"] == 4
    assert lowest["attacker_recall"] == max(row["attacker_recall"] for row in counts)
    assert lowest["legitimate_false_positive_rate"] == max(
        row["legitimate_false_positive_rate"] for row in counts
    )
