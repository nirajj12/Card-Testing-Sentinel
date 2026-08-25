from collections import defaultdict

import numpy as np
import pandas as pd

from card_testing_sentinel.v2.data.contracts import LifecycleEvent
from card_testing_sentinel.v2.evaluation.metrics import wilson_interval
from card_testing_sentinel.v2.features.engine import CausalFeatureEngine
from card_testing_sentinel.v2.features.spec import MODEL_FEATURES
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.policy.rules import evaluate_rules
from card_testing_sentinel.v2.policy.selection import choose_action


def lifecycle_event(record: dict) -> LifecycleEvent:
    payload = {key: value for key, value in record.items() if key in LifecycleEvent.model_fields and pd.notna(value)}
    if "card_bin" in payload:
        payload["card_bin"] = str(payload["card_bin"]).removesuffix(".0")
    return LifecycleEvent.model_validate(payload)


def replay_policy(raw: pd.DataFrame, artifact, candidate: dict, device_contract: pd.DataFrame):
    engine = CausalFeatureEngine()
    blocked_devices: set[str] = set()
    blocked_requests: set[str] = set()
    request_indexes = defaultdict(int)
    first_request_time = {}
    requested_cards = defaultdict(set)
    decisions = []
    potentially_preventable = defaultdict(int)
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    for record in ordered.to_dict("records"):
        event = lifecycle_event(record)
        if event.device_id in blocked_devices:
            if event.event_type == "authorization_request":
                request_indexes[event.device_id] += 1
                potentially_preventable[event.device_id] += 1
                decisions.append(
                    {
                        "event_id": event.event_id,
                        "request_id": event.request_id,
                        "device_id": event.device_id,
                        "timestamp": event.timestamp.isoformat(),
                        "request_index": request_indexes[event.device_id],
                        "raw_probability": np.nan,
                        "calibrated_probability": np.nan,
                        "rule_score": np.nan,
                        "action": "counterfactual_after_block",
                        "reason_codes": "",
                        "state_version": np.nan,
                        "processed_authorizations_before_action": np.nan,
                        "distinct_cards_requested_through_action": np.nan,
                        "distinct_cards_processed_before_action": np.nan,
                        "seconds_to_action": np.nan,
                        "counterfactual_after_block": True,
                    }
                )
            continue
        if event.event_type == "authorization_request":
            request_indexes[event.device_id] += 1
            first_request_time.setdefault(event.device_id, event.timestamp)
            requested_cards[event.device_id].add(event.card_fingerprint)
            processed = engine.devices[event.device_id].processed
            processed_cards = {row.card_fingerprint for row in processed}
            # Score the current request before its future outcome exists.
            snapshot = engine._snapshot(event, engine.devices[event.device_id])
            model_frame = pd.DataFrame([{name: snapshot[name] for name in MODEL_FEATURE_COLUMNS}], columns=MODEL_FEATURE_COLUMNS)
            raw_probability = float(artifact.predict_raw_proba(model_frame)[0])
            probability = float(artifact.predict_proba(model_frame)[0])
            rule_score, reasons = evaluate_rules(snapshot)
            action = choose_action(candidate, probability, rule_score)
            committed = engine.precheck(event, blocked=action == "block_current_attempt")
            decisions.append(
                {
                    "event_id": event.event_id,
                    "request_id": event.request_id,
                    "device_id": event.device_id,
                    "timestamp": event.timestamp.isoformat(),
                    "request_index": request_indexes[event.device_id],
                    "raw_probability": raw_probability,
                    "calibrated_probability": probability,
                    "rule_score": rule_score,
                    "action": action,
                    "reason_codes": "|".join(reasons),
                    "state_version": committed["state_version"],
                    "processed_authorizations_before_action": len(processed),
                    "distinct_cards_requested_through_action": len(requested_cards[event.device_id]),
                    "distinct_cards_processed_before_action": len(processed_cards),
                    "seconds_to_action": (event.timestamp - first_request_time[event.device_id]).total_seconds(),
                    "counterfactual_after_block": False,
                }
            )
            if action == "block_current_attempt":
                blocked_devices.add(event.device_id)
                blocked_requests.add(event.request_id)
        elif event.event_type == "authorization_outcome":
            if event.request_id not in blocked_requests:
                engine.record_outcome(event)
        else:
            if event.request_id not in blocked_requests:
                engine.record_completion(event)
    decisions_frame = pd.DataFrame(decisions)
    devices = summarize_devices(decisions_frame, device_contract, potentially_preventable)
    return decisions_frame, devices


def summarize_devices(decisions: pd.DataFrame, contract: pd.DataFrame, potentially_preventable: dict) -> pd.DataFrame:
    rows = []
    for device in contract.itertuples(index=False):
        group = decisions.loc[decisions.device_id.eq(device.device_id)].sort_values("request_index")
        observed = group.loc[~group.counterfactual_after_block]
        reviewed = observed.loc[observed.action.isin(["review", "block_current_attempt"])]
        blocked = observed.loc[observed.action.eq("block_current_attempt")]
        first_action = reviewed.iloc[0] if len(reviewed) else None
        first_block = blocked.iloc[0] if len(blocked) else None
        rows.append(
            {
                "device_id": device.device_id,
                "label": int(device.label),
                "population": device.population,
                "attack_subtype": device.attack_subtype,
                "scenario_tag": device.scenario_tag,
                "review_or_higher": bool(len(reviewed)),
                "blocked": bool(len(blocked)),
                "first_action": first_action.action if first_action is not None else "never",
                "first_review_or_higher_request": int(first_action.request_index) if first_action is not None else np.nan,
                "first_block_request": int(first_block.request_index) if first_block is not None else np.nan,
                "requests_scored_through_first_action": int(first_action.request_index) if first_action is not None else int(len(observed)),
                "authorizations_processed_before_first_action": int(first_action.processed_authorizations_before_action) if first_action is not None else int(len(observed)),
                "distinct_cards_requested_through_first_action": int(first_action.distinct_cards_requested_through_action) if first_action is not None else np.nan,
                "distinct_cards_processed_before_first_action": int(first_action.distinct_cards_processed_before_action) if first_action is not None else np.nan,
                "seconds_to_first_review": float(first_action.seconds_to_action) if first_action is not None else np.nan,
                "seconds_to_first_block": float(first_block.seconds_to_action) if first_block is not None else np.nan,
                "potentially_preventable_later_requests_upper_bound": int(potentially_preventable.get(device.device_id, 0)),
            }
        )
    return pd.DataFrame(rows)


def proportion(group: pd.DataFrame, column: str) -> dict:
    numerator = int(group[column].sum())
    denominator = int(len(group))
    low, high = wilson_interval(numerator, denominator)
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else np.nan, "wilson_95_low": low, "wilson_95_high": high}


def candidate_metrics(devices: pd.DataFrame, budgets: dict) -> dict:
    attackers = devices.loc[devices.label.eq(1)]
    legitimate = devices.loc[devices.label.eq(0)]
    subtype_review = {str(name): proportion(group, "review_or_higher") for name, group in attackers.groupby("attack_subtype")}
    subtype_block = {str(name): proportion(group, "blocked") for name, group in attackers.groupby("attack_subtype")}
    review_values = [row["rate"] for row in subtype_review.values()]
    block_values = [row["rate"] for row in subtype_block.values()]
    budget_results = {}
    for name, budget in budgets.items():
        group = legitimate if name == "overall_legitimate" else legitimate.loc[legitimate.scenario_tag.eq(name)]
        review_count = int(group.review_or_higher.sum())
        block_count = int(group.blocked.sum())
        budget_results[name] = {
            "denominator": int(len(group)),
            "review_or_higher": review_count,
            "review_allowance": int(budget["review_or_higher_allowance"]),
            "block": block_count,
            "block_allowance": int(budget["block_allowance"]),
            "passed": review_count <= budget["review_or_higher_allowance"] and block_count <= budget["block_allowance"],
        }
    acted_attackers = attackers.loc[attackers.review_or_higher]
    return {
        "feasible": all(row["passed"] for row in budget_results.values()),
        "budgets": budget_results,
        "attacker_review_or_higher": proportion(attackers, "review_or_higher"),
        "attacker_block": proportion(attackers, "blocked"),
        "subtype_review": subtype_review,
        "subtype_block": subtype_block,
        "worst_subtype_review_coverage": min(review_values),
        "macro_subtype_review_coverage": float(np.mean(review_values)),
        "worst_subtype_block_coverage": min(block_values),
        "macro_subtype_block_coverage": float(np.mean(block_values)),
        "median_processed_authorizations_before_first_action": float(acted_attackers.authorizations_processed_before_first_action.median()) if len(acted_attackers) else np.nan,
        "legitimate_review_or_higher": int(legitimate.review_or_higher.sum()),
        "legitimate_blocks": int(legitimate.blocked.sum()),
        "potentially_preventable_later_requests_upper_bound": int(devices.potentially_preventable_later_requests_upper_bound.sum()),
    }
