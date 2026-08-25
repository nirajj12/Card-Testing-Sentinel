import pandas as pd

from card_testing_sentinel.policy import selection
from card_testing_sentinel.policy.selection import _better_key, budget_checks


def test_integer_device_budgets_and_subgroup_guardrails():
    summary = pd.DataFrame(
        {
            "label": [0] * 10,
            "population": ["flash_sale"] * 3 + ["normal"] * 7,
            "scenario_exposures": ["flash_hard_retry"] * 2
            + ["flash_typical"]
            + ["normal_bad_luck"] * 2
            + ["normal_standard"] * 5,
            "ever_review_or_higher": [True] + [False] * 9,
            "ever_blocked": [True] + [False] * 9,
        }
    )
    config = {
        "maximum_legitimate_device_review_or_higher_rate": 0.05,
        "maximum_legitimate_device_block_rate": 0.01,
        "subgroup_block_guardrails": {
            "flash_sale": 0.03,
            "flash_hard_retry": 0.15,
            "normal_bad_luck": 0.10,
        },
    }
    checks = budget_checks(summary, config)
    assert checks["legitimate_block"]["maximum_allowed_devices"] == 0
    assert checks["legitimate_block"]["passed"] is False
    assert checks["flash_hard_retry_block"]["denominator_devices"] == 2
    assert checks["flash_hard_retry_block"]["rate_granularity"] == 0.5


def test_legacy_better_key_prefers_coverage_delay_hard_retry_then_thresholds():
    base = {
        "metrics": {
            "attacker_block_coverage": {"rate": 0.5},
            "detection_attempt_position": {"median": 4.0},
        },
        "budgets": {"flash_hard_retry_block": {"numerator_devices": 1, "rate": 0.1}},
        "thresholds": {"rule_block_score": 3},
    }
    faster = {
        **base,
        "metrics": {
            "attacker_block_coverage": {"rate": 0.5},
            "detection_attempt_position": {"median": 3.0},
        },
    }
    higher_coverage = {
        **base,
        "metrics": {
            "attacker_block_coverage": {"rate": 0.6},
            "detection_attempt_position": {"median": 20.0},
        },
    }
    assert _better_key(higher_coverage) > _better_key(faster) > _better_key(base)


def test_legacy_select_policies_prefers_rules_on_an_exact_cross_method_tie(
    monkeypatch,
):
    events = pd.DataFrame({"rule_score": [1], "risk_score": [0.5]})

    def result(method, thresholds):
        return {
            "method": method,
            "thresholds": thresholds,
            "feasible": True,
            "metrics": {
                "attacker_block_coverage": {"rate": 0.5},
                "detection_attempt_position": {"median": 4.0},
            },
            "budgets": {
                "flash_hard_retry_block": {
                    "numerator_devices": 0,
                    "rate": 0.0,
                }
            },
        }

    monkeypatch.setattr(
        selection,
        "_fast_candidate",
        lambda events, method, thresholds, config: result(method, thresholds),
    )
    monkeypatch.setattr(
        selection,
        "evaluate_policy",
        lambda events, method, thresholds, config: result(method, thresholds),
    )
    selected = selection.select_policies(events, {"ml_threshold_quantiles": [0.5]})
    assert selected["champion"] == "rules_only"
    assert selected["candidate_counts"] == {
        "rules_only": {"evaluated": 1, "feasible": 1},
        "ml_only": {"evaluated": 1, "feasible": 1},
        "combined": {"evaluated": 1, "feasible": 1},
    }
