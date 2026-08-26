"""Causal intervention replay and Phase 2C device-level metrics."""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from card_testing_sentinel.v2.phase2b.batch import lifecycle_event
from card_testing_sentinel.v2.phase2b.engine import Phase2BFeatureEngine
from card_testing_sentinel.v2.phase2b.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.phase2c.policy import StatefulPolicy


def _initial_stats(contract: pd.DataFrame) -> dict[str, dict]:
    result = {}
    for row in contract.to_dict("records"):
        result[str(row["device_id"])] = {
            "device_id": str(row["device_id"]),
            "label": int(row["label"]),
            "population": row["population"],
            "attack_subtype": row.get("attack_subtype"),
            "scenario_tag": row["scenario_tag"],
            "request_index": 0,
            "first_request_time": None,
            "requested_cards": set(),
            "review_or_higher": False,
            "blocked": False,
            "first_action": "never",
            "first_review_or_higher_request": np.nan,
            "first_block_request": np.nan,
            "requests_scored_through_first_action": np.nan,
            "authorizations_processed_before_first_action": np.nan,
            "distinct_cards_requested_through_first_action": np.nan,
            "distinct_cards_processed_before_first_action": np.nan,
            "seconds_to_first_review": np.nan,
            "seconds_to_first_block": np.nan,
            "potentially_preventable_later_requests_upper_bound": 0,
        }
    return result


def replay_stateful_candidate(
    raw: pd.DataFrame,
    contract: pd.DataFrame,
    scorer,
    candidate: dict,
    *,
    capture_decisions: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Replay one candidate from empty feature and policy state.

    A block applies only to the current request. Its request-side observation
    (request time, session, IP request activity, and pending blocked marker) is
    committed, while its processor outcome and dependent checkout completion
    are suppressed. Every later authorization request is feature-computed and
    scored from that changed state. Phase 2C has no permanent-device action.
    """
    engine = Phase2BFeatureEngine()
    policy = StatefulPolicy(candidate)
    stats = _initial_stats(contract)
    blocked_requests: set[str] = set()
    decisions: list[dict] = []
    reasons: Counter[str] = Counter()
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    for record in ordered.to_dict("records"):
        event = lifecycle_event(record)
        device_stats = stats[event.device_id]
        if event.event_type == "authorization_request":
            if device_stats["blocked"]:
                device_stats["potentially_preventable_later_requests_upper_bound"] += 1
            device_stats["request_index"] += 1
            device_stats["first_request_time"] = (
                device_stats["first_request_time"] or event.timestamp
            )
            device_stats["requested_cards"].add(event.card_fingerprint)
            feature_state = engine.devices[event.device_id]
            processed_before = len(feature_state.processed)
            processed_cards = {row.card_fingerprint for row in feature_state.processed}
            snapshot = {
                **engine._snapshot(event, feature_state),
                **engine._phase2b_snapshot(event),
            }
            raw_probability, calibrated = scorer.score_snapshot(snapshot)
            decision = policy.decide(
                device_id=event.device_id,
                event_id=event.event_id,
                timestamp=event.timestamp,
                session_id=event.session_id,
                probability=calibrated,
                snapshot=snapshot,
            )
            committed = engine.precheck(event, blocked=decision.action == "block")
            if any(committed[name] != snapshot[name] for name in MODEL_FEATURE_COLUMNS):
                raise RuntimeError("decision did not use immediate precheck state")
            reasons.update(decision.reason_codes)
            seconds = (
                event.timestamp - device_stats["first_request_time"]
            ).total_seconds()
            if (
                decision.action in {"review", "block"}
                and not device_stats["review_or_higher"]
            ):
                device_stats.update(
                    {
                        "review_or_higher": True,
                        "first_action": decision.action,
                        "first_review_or_higher_request": device_stats["request_index"],
                        "requests_scored_through_first_action": device_stats[
                            "request_index"
                        ],
                        "authorizations_processed_before_first_action": (
                            processed_before
                        ),
                        "distinct_cards_requested_through_first_action": len(
                            device_stats["requested_cards"]
                        ),
                        "distinct_cards_processed_before_first_action": len(
                            processed_cards
                        ),
                        "seconds_to_first_review": seconds,
                    }
                )
            if decision.action == "block":
                if not device_stats["blocked"]:
                    device_stats["blocked"] = True
                    device_stats["first_block_request"] = device_stats["request_index"]
                    device_stats["seconds_to_first_block"] = seconds
                blocked_requests.add(event.request_id)
            if capture_decisions:
                decisions.append(
                    {
                        "event_id": event.event_id,
                        "request_id": event.request_id,
                        "device_id": event.device_id,
                        "request_index": device_stats["request_index"],
                        "action": decision.action,
                        "raw_probability": raw_probability,
                        "calibrated_probability": calibrated,
                        "rule_score": decision.rule_score,
                        "accumulated_risk": decision.accumulated_risk,
                        "high_risk_count": decision.high_risk_count,
                        "consecutive_high_count": decision.consecutive_high_count,
                        "evidence_count": decision.evidence_count,
                        "reason_codes": "|".join(decision.reason_codes),
                    }
                )
        elif event.event_type == "authorization_outcome":
            if event.request_id not in blocked_requests:
                engine.record_outcome(event)
        elif event.request_id not in blocked_requests:
            engine.record_completion(event)
    rows = []
    for state in stats.values():
        if np.isnan(state["requests_scored_through_first_action"]):
            state["requests_scored_through_first_action"] = state["request_index"]
            state["authorizations_processed_before_first_action"] = len(
                engine.devices[state["device_id"]].processed
            )
        rows.append(
            {key: value for key, value in state.items() if key != "requested_cards"}
        )
    audit = {
        "requests_generated": int(raw.event_type.eq("authorization_request").sum()),
        "requests_scored": int(sum(row["request_index"] for row in stats.values())),
        "blocked_outcomes_suppressed": len(blocked_requests),
        "dependent_checkout_events_suppressed": int(
            raw.loc[
                raw.event_type.eq("checkout_completion")
                & raw.request_id.isin(blocked_requests)
            ].shape[0]
        ),
        "reason_code_frequencies": dict(sorted(reasons.items())),
        "feature_state_scope": "fresh_per_candidate",
        "policy_state_scope": "fresh_per_candidate",
    }
    return pd.DataFrame(decisions), pd.DataFrame(rows), audit


def _rate(group: pd.DataFrame, column: str) -> dict:
    numerator = int(group[column].sum())
    denominator = int(len(group))
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def integer_budgets(devices: pd.DataFrame, safety_rates: dict) -> dict:
    legitimate = devices.loc[devices.label.eq(0)]
    budgets = {}
    for name, rates in safety_rates.items():
        group = (
            legitimate
            if name == "overall_legitimate"
            else legitimate.loc[legitimate.scenario_tag.eq(name)]
        )
        budgets[name] = {
            "review_or_higher_allowance": int(
                np.floor(len(group) * float(rates["review_or_higher_rate"]))
            ),
            "block_allowance": int(np.floor(len(group) * float(rates["block_rate"]))),
        }
    return budgets


def candidate_metrics(
    devices: pd.DataFrame,
    safety_rates: dict,
    effectiveness_targets: dict,
) -> dict:
    attackers = devices.loc[devices.label.eq(1)]
    legitimate = devices.loc[devices.label.eq(0)]
    budgets = integer_budgets(devices, safety_rates)
    budget_results = {}
    safety_failures: list[str] = []
    for name, budget in budgets.items():
        group = (
            legitimate
            if name == "overall_legitimate"
            else legitimate.loc[legitimate.scenario_tag.eq(name)]
        )
        reviewed = int(group.review_or_higher.sum())
        blocked = int(group.blocked.sum())
        result = {
            "denominator_devices": int(len(group)),
            "review_or_higher_devices": reviewed,
            "review_only_devices": reviewed - blocked,
            "block_devices": blocked,
            "review_allowance_devices": budget["review_or_higher_allowance"],
            "block_allowance_devices": budget["block_allowance"],
            "review_excess_devices": max(
                0, reviewed - budget["review_or_higher_allowance"]
            ),
            "block_excess_devices": max(0, blocked - budget["block_allowance"]),
        }
        result["passed"] = not (
            result["review_excess_devices"] or result["block_excess_devices"]
        )
        if result["review_excess_devices"]:
            safety_failures.append(
                f"{name}:review_excess={result['review_excess_devices']}"
            )
        if result["block_excess_devices"]:
            safety_failures.append(
                f"{name}:block_excess={result['block_excess_devices']}"
            )
        budget_results[name] = result

    subtype = {}
    for name, group in attackers.groupby("attack_subtype", sort=True):
        subtype[str(name)] = {
            "review_or_higher": _rate(group, "review_or_higher"),
            "block": _rate(group, "blocked"),
            "never_detected": int((~group.review_or_higher).sum()),
            "within_attempt": {
                str(limit): {
                    "review_or_higher": int(
                        group.first_review_or_higher_request.le(limit).sum()
                    ),
                    "block": int(group.first_block_request.le(limit).sum()),
                    "denominator": int(len(group)),
                }
                for limit in (1, 3, 5, 10)
            },
        }
    overall_review = _rate(attackers, "review_or_higher")
    overall_block = _rate(attackers, "blocked")
    actual = {
        "overall_review_or_higher": overall_review["rate"],
        "overall_block": overall_block["rate"],
        "burst_review_or_higher": subtype["burst"]["review_or_higher"]["rate"],
        "evasive_review_or_higher": subtype["evasive"]["review_or_higher"]["rate"],
        "patient_review_or_higher": subtype["patient"]["review_or_higher"]["rate"],
    }
    effectiveness_results = {}
    effectiveness_failures = []
    for name, target in effectiveness_targets.items():
        passed = actual[name] >= float(target)
        effectiveness_results[name] = {
            "actual": actual[name],
            "minimum": float(target),
            "passed": passed,
        }
        if not passed:
            effectiveness_failures.append(
                f"{name}:shortfall={float(target) - actual[name]:.12g}"
            )
    acted = attackers.loc[attackers.review_or_higher]
    distributions = {}
    for column in (
        "requests_scored_through_first_action",
        "authorizations_processed_before_first_action",
        "distinct_cards_requested_through_first_action",
        "distinct_cards_processed_before_first_action",
        "seconds_to_first_review",
    ):
        values = acted[column].dropna()
        distributions[column] = {
            "count": int(len(values)),
            "median": float(values.median()) if len(values) else None,
            "mean": float(values.mean()) if len(values) else None,
            "p90": float(values.quantile(0.9)) if len(values) else None,
        }
    failed = [*safety_failures, *effectiveness_failures]
    return {
        "feasible": not failed,
        "safety_passed": not safety_failures,
        "effectiveness_passed": not effectiveness_failures,
        "failed_constraints": failed,
        "safety_failures": safety_failures,
        "effectiveness_failures": effectiveness_failures,
        "budget_results": budget_results,
        "effectiveness_results": effectiveness_results,
        "attacker_review_or_higher": overall_review,
        "attacker_block": overall_block,
        "subtype": subtype,
        "worst_subtype_review_coverage": min(
            row["review_or_higher"]["rate"] for row in subtype.values()
        ),
        "never_detected_attackers": int((~attackers.review_or_higher).sum()),
        "legitimate_review_or_higher": int(legitimate.review_or_higher.sum()),
        "legitimate_blocks": int(legitimate.blocked.sum()),
        "within_attempt": {
            str(limit): {
                "review_or_higher": int(
                    attackers.first_review_or_higher_request.le(limit).sum()
                ),
                "block": int(attackers.first_block_request.le(limit).sum()),
                "denominator": int(len(attackers)),
            }
            for limit in (1, 3, 5, 10)
        },
        "intervention_distributions": distributions,
        "potentially_preventable_later_attempts_offline_upper_bound": int(
            devices.potentially_preventable_later_requests_upper_bound.sum()
        ),
    }


def selection_key(candidate: dict, metrics: dict) -> tuple:
    median = metrics["intervention_distributions"][
        "requests_scored_through_first_action"
    ]["median"]
    return (
        -metrics["worst_subtype_review_coverage"],
        -metrics["attacker_block"]["rate"],
        float("inf") if median is None else median,
        metrics["legitimate_blocks"],
        metrics["legitimate_review_or_higher"],
        policy_complexity(candidate),
        candidate["candidate_id"],
    )


def policy_complexity(candidate: dict) -> int:
    family_cost = {
        "rules_only": 0,
        "persistent_ml": 1,
        "consecutive_high": 2,
        "accumulated_decay": 3,
        "long_term_corroborated": 4,
        "campaign_aware": 5,
        "checkout_protected": 5,
    }
    nondefault = sum(
        value not in (None, 0, 0.0, False, "")
        for key, value in candidate.items()
        if key not in {"candidate_id", "family"}
    )
    return family_cost[candidate["family"]] * 100 + nondefault


def fold_stability(fold_metrics: list[dict], spec: dict) -> dict:
    failures = []
    reviews = []
    for row in fold_metrics:
        metrics = row["metrics"]
        values = {
            "overall_review_or_higher": metrics["attacker_review_or_higher"]["rate"],
            "overall_block": metrics["attacker_block"]["rate"],
            "burst_review_or_higher": metrics["subtype"]["burst"]["review_or_higher"][
                "rate"
            ],
            "evasive_review_or_higher": metrics["subtype"]["evasive"][
                "review_or_higher"
            ]["rate"],
            "patient_review_or_higher": metrics["subtype"]["patient"][
                "review_or_higher"
            ]["rate"],
        }
        reviews.append(values["overall_review_or_higher"])
        for name, value in values.items():
            minimum = float(spec[f"minimum_{name}"])
            if value < minimum:
                failures.append(
                    f"fold_{row['fold']}:{name}:shortfall={minimum - value:.12g}"
                )
    review_range = max(reviews) - min(reviews)
    if review_range > float(spec["maximum_overall_review_range"]):
        failures.append(f"overall_review_fold_range={review_range:.12g}")
    return {
        "passed": not failures,
        "failures": failures,
        "overall_review_range": review_range,
        "folds": len(fold_metrics),
    }
