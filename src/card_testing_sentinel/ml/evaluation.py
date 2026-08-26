"""Model metrics and sequential operational-policy evaluation."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import joblib
import pandas as pd

from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.features.engine import CausalFeatureEngine
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.metrics import probability_metrics
from card_testing_sentinel.ml.weights import device_evaluation_weights
from card_testing_sentinel.policy.engine import OperationalPolicy


def _event(record: dict) -> LifecycleEvent:
    payload = {
        key: value
        for key, value in record.items()
        if key in LifecycleEvent.model_fields and pd.notna(value)
    }
    if "card_bin" in payload:
        payload["card_bin"] = str(payload["card_bin"]).removesuffix(".0")
    return LifecycleEvent.model_validate(payload)


def evaluate_validation_rows(model_path: Path, feature_path: Path) -> dict:
    """Evaluate a development model on its untouched device validation split."""
    artifact = joblib.load(model_path)
    frame = pd.read_csv(feature_path)
    validation = frame.loc[frame.split.eq("validation")].reset_index(drop=True)
    raw_scores = artifact.predict_raw_proba(validation)
    risk_scores = artifact.predict_proba(validation)
    weights = device_evaluation_weights(validation)
    return {
        "status": "validation_evaluated",
        "devices": int(validation.device_id.nunique()),
        "rows": int(len(validation)),
        "raw_model": probability_metrics(validation.label, raw_scores, weights),
        "calibrated_risk": probability_metrics(validation.label, risk_scores, weights),
        "blind_evidence_read": False,
    }


def replay_operational_policy(
    raw_events: pd.DataFrame,
    artifact,
    policy_values: dict,
) -> pd.DataFrame:
    """Replay live causal semantics without terminating a device after a block."""
    engine = CausalFeatureEngine()
    policy = OperationalPolicy(policy_values)
    blocked_requests: set[str] = set()
    request_indexes: defaultdict[str, int] = defaultdict(int)
    decisions = []
    ordered = raw_events.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    for record in ordered.to_dict("records"):
        event = _event(record)
        if event.event_type == "authorization_request":
            state = engine.devices[event.device_id]
            snapshot = {
                **engine._snapshot(event, state),
                **engine._extended_snapshot(event),
            }
            frame = pd.DataFrame(
                [[snapshot[name] for name in MODEL_FEATURES]],
                columns=MODEL_FEATURES,
            )
            raw_score = float(artifact.predict_raw_proba(frame)[0])
            risk_score = float(artifact.predict_proba(frame)[0])
            decision = policy.decide(
                device_id=event.device_id,
                event_id=event.event_id,
                timestamp=event.timestamp,
                session_id=event.session_id,
                risk_score=risk_score,
                snapshot=snapshot,
            )
            committed = engine.precheck(event, blocked=decision.action == "block")
            request_indexes[event.device_id] += 1
            if decision.action == "block":
                blocked_requests.add(event.request_id)
            decisions.append(
                {
                    "event_id": event.event_id,
                    "request_id": event.request_id,
                    "device_id": event.device_id,
                    "request_index": request_indexes[event.device_id],
                    "timestamp": event.timestamp.isoformat(),
                    "raw_model_score": raw_score,
                    "risk_score": risk_score,
                    "rule_score": decision.rule_score,
                    "decision": decision.action,
                    "reason_codes": "|".join(decision.reason_codes),
                    "state_version": committed["state_version"],
                    "label": record.get("label"),
                    "population": record.get("population"),
                    "attack_subtype": record.get("attack_subtype"),
                    "scenario_tag": record.get("scenario_tag"),
                }
            )
        elif event.request_id in blocked_requests:
            continue
        elif event.event_type == "authorization_outcome":
            engine.record_outcome(event)
        else:
            engine.record_completion(event)
    return pd.DataFrame(decisions)


def summarize_sequential_decisions(decisions: pd.DataFrame) -> dict:
    device = decisions.sort_values("request_index").groupby("device_id", sort=False)
    summary = device.agg(
        label=("label", "first"),
        population=("population", "first"),
        attack_subtype=("attack_subtype", "first"),
        requests=("request_id", "size"),
        reviewed=(
            "decision",
            lambda values: bool(values.isin(["review", "block"]).any()),
        ),
        blocked=("decision", lambda values: bool(values.eq("block").any())),
    )
    first_review = (
        decisions.loc[decisions.decision.isin(["review", "block"])]
        .groupby("device_id")
        .request_index.min()
    )
    first_block = (
        decisions.loc[decisions.decision.eq("block")]
        .groupby("device_id")
        .request_index.min()
    )
    summary["first_review_request"] = first_review
    summary["first_block_request"] = first_block
    attackers = summary.loc[summary.label.eq(1)]
    legitimate = summary.loc[summary.label.eq(0)]
    return {
        "devices": int(len(summary)),
        "attacker_review_coverage": float(attackers.reviewed.mean()),
        "attacker_block_coverage": float(attackers.blocked.mean()),
        "legitimate_review_rate": float(legitimate.reviewed.mean()),
        "legitimate_block_rate": float(legitimate.blocked.mean()),
        "median_first_review": float(first_review.median()),
        "median_first_block": float(first_block.median()),
    }
