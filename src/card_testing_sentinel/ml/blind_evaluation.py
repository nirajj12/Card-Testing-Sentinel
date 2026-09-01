"""One-time blind benchmark evaluation.

This module applies the **frozen** model and the **frozen** policy to a frozen
blind benchmark and reports pre-registered metrics. Nothing here fits, refits,
recalibrates, sweeps or selects: there is no `.fit()` call, no calibrator
construction and no threshold search anywhere on this path, and tests assert
that by reading the source.

Every metric definition is imported from the modules that produced the
validation numbers (`ml.metrics`, `ml.evaluation`) or applies the policy
through the same replay used to select it (`ml.policy_search.replay`), so a
validation-versus-blind delta cannot be an artifact of a redefined metric.
The *selection* functions in `policy_search` (`candidate_configs`,
`evaluate_candidates`, `select`) are never called.

Consumption is one-way and is recorded **before** the first score is produced,
not after the report is written: a crashed evaluation still spends the
benchmark, because the scores existed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.blind_generator import BlindBenchmarkError
from card_testing_sentinel.policy.engine import RiskPolicy
from card_testing_sentinel.policy.evidence import evidence_codes

#: Keys copied verbatim out of the frozen policy artifact. Duplicating the
#: numbers in evaluation code would let them drift from the artifact.
POLICY_KEYS = (
    "family",
    "review_threshold",
    "block_threshold",
    "block_evidence",
    "block_elevated_count",
    "persistence_window_hours",
    "history_cap",
    "block_ttl_seconds",
    "campaign_review_increment",
    "campaign_block_increment",
    "degraded_review_rule_score",
    "degraded_block_rule_score",
)

#: Merchant generalisation categories. `travel` is deliberately its own
#: category: it is declared in the development config but **no travel merchant
#: was ever realized** in the frozen development data, so the model has never
#: seen it. Counting it as "known" would overstate familiarity.
MERCHANT_CATEGORY = {
    "A_seen_in_development": (
        "small_ecommerce",
        "digital_goods",
        "subscription",
        "electronics",
        "education",
        "flash_sale",
    ),
    "B_declared_but_unrealized_in_development": ("travel",),
    "C_new_blind_only_kind": ("ticketing_events", "food_delivery", "gaming_topups"),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# one-way consumption
# --------------------------------------------------------------------------


def mark_evaluation_started(freeze_manifest: Path, blind_version: str) -> str:
    """Spend the benchmark, then return the evaluation timestamp.

    Called *before* the first score. If this raises, no score was produced;
    if it succeeds, the benchmark is consumed whatever happens next.
    """
    manifest = json.loads(freeze_manifest.read_text())
    if manifest.get("consumed") or manifest.get("blind_evaluated"):
        raise BlindBenchmarkError(
            f"blind {manifest.get('blind_version')} is already consumed; a "
            "second untouched-benchmark evaluation is not possible. A changed "
            "model or policy needs blind v2 with a new seed and spec revision."
        )
    if manifest.get("blind_version") != blind_version:
        raise BlindBenchmarkError(
            f"freeze records {manifest.get('blind_version')}, not {blind_version}"
        )
    started = datetime.now(UTC).isoformat()
    manifest["consumed"] = True
    manifest["evaluation_started_utc"] = started
    manifest["consumption_note"] = (
        "Consumed at the moment the frozen model was first scored against "
        f"blind {blind_version}. This flag is set BEFORE the metrics are "
        "written, so an interrupted evaluation still spends the benchmark."
    )
    freeze_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return started


def mark_evaluation_complete(freeze_manifest: Path, metrics_path: Path) -> None:
    manifest = json.loads(freeze_manifest.read_text())
    manifest["blind_evaluated"] = True
    manifest["evaluation_completed_utc"] = datetime.now(UTC).isoformat()
    manifest["blind_metrics_file"] = metrics_path.name
    manifest["blind_metrics_sha256"] = sha256_file(metrics_path)
    freeze_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# frozen artifacts
# --------------------------------------------------------------------------


def load_frozen_model(path: Path, expected_sha256: str):
    """Load the exact frozen artifact, refusing anything else."""
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise BlindBenchmarkError(
            f"model artifact hash {actual} does not match the frozen "
            f"{expected_sha256}; the blind evaluation must use the frozen model"
        )
    import joblib

    return joblib.load(path)


def frozen_policy(artifact: dict) -> RiskPolicy:
    """Build the policy from the frozen artifact's own numbers."""
    return RiskPolicy({key: artifact[key] for key in POLICY_KEYS})


def verify_frozen_inputs(root: Path, freeze: dict) -> dict:
    """Re-check every hash the evaluation depends on."""
    checked: dict[str, str] = {}
    for stage in ("development", "blind", "dataset"):
        section = freeze.get(stage, {})
        for key, name in section.get("files", {}).items():
            actual = sha256_file(root / name)
            if actual != section[key]:
                raise BlindBenchmarkError(f"{name} changed since the freeze")
            checked[f"{stage}.{key}"] = actual
    return checked


# --------------------------------------------------------------------------
# policy diagnostics
# --------------------------------------------------------------------------


def evidence_gate_analysis(
    frame: pd.DataFrame, replayed: pd.DataFrame, policy: RiskPolicy
) -> dict:
    """Did the evidence gate actually stop any block under blind shift?

    Diagnostic only. On validation the gate was behaviourally redundant --
    every device that crossed the block threshold also carried two evidence
    codes. Blind is the first chance to see whether that holds off the
    distribution it was chosen on.
    """
    snapshots = frame.loc[:, list(MODEL_FEATURES)].to_dict("records")
    working = replayed.copy()
    block_at = policy.block_threshold + np.where(
        working.campaign_active.to_numpy(dtype=bool),
        policy.campaign_block_increment,
        0.0,
    )
    working["high_score"] = working.risk.to_numpy(dtype=float) >= block_at
    working["evidence_count"] = [
        len(evidence_codes(snapshots[index])) for index in working.row_index
    ]
    working["gate_blocked_it"] = working.high_score & working.action.ne("block")

    device = working.groupby("device_id").agg(
        label=("label", "first"),
        population=("population", "first"),
        scenario=("scenario", "first"),
        ever_high_score=("high_score", "any"),
        ever_blocked=("action", lambda actions: bool((actions == "block").any())),
        max_evidence_when_high=(
            "evidence_count",
            "max",
        ),
    )
    withheld = device.loc[device.ever_high_score & ~device.ever_blocked]
    rows = working.loc[working.gate_blocked_it]
    return {
        "note": (
            "Diagnostic only; the gate was not changed. A device counts as "
            "'withheld' if some attempt scored at or above the (campaign "
            "adjusted) block threshold and the device was never blocked."
        ),
        "attempts_at_or_above_block_threshold": int(working.high_score.sum()),
        "attempts_withheld_by_evidence_gate": int(working.gate_blocked_it.sum()),
        "devices_reaching_block_score": int(device.ever_high_score.sum()),
        "devices_withheld_by_evidence_gate": int(len(withheld)),
        "devices_withheld_legitimate": int((withheld.label == 0).sum()),
        "devices_withheld_attack": int((withheld.label == 1).sum()),
        "withheld_legitimate_scenarios": (
            withheld.loc[withheld.label.eq(0)].scenario.value_counts().to_dict()
        ),
        "withheld_attack_scenarios": (
            withheld.loc[withheld.label.eq(1)].scenario.value_counts().to_dict()
        ),
        "evidence_count_on_withheld_attempts": (
            rows.evidence_count.value_counts().sort_index().to_dict()
        ),
        "required_evidence": policy.block_evidence,
    }


def campaign_comparison(replayed: pd.DataFrame) -> list[dict]:
    """Policy behaviour inside versus outside a merchant campaign.

    Split at device level by whether the device ever transacted while its
    merchant was running a campaign, because the policy decision is
    device-sequential.
    """
    working = replayed.copy()
    working["rank"] = working.action.map({"allow": 0, "review": 1, "block": 2})
    device = working.groupby("device_id").agg(
        label=("label", "first"),
        in_campaign=("campaign_active", "any"),
        max_action=("rank", "max"),
    )
    device["ever_reviewed"] = device.max_action >= 1
    device["ever_blocked"] = device.max_action >= 2
    rows = []
    for flag in (True, False):
        group = device.loc[device.in_campaign.eq(flag)]
        attack = group.loc[group.label.eq(1)]
        legitimate = group.loc[group.label.eq(0)]
        rows.append(
            {
                "campaign_active": bool(flag),
                "devices": int(len(group)),
                "attack_devices": int(len(attack)),
                "legitimate_devices": int(len(legitimate)),
                "attack_review_or_higher_recall": _rate(attack.ever_reviewed),
                "attack_block_recall": _rate(attack.ever_blocked),
                "legitimate_review_or_higher_rate": _rate(legitimate.ever_reviewed),
                "legitimate_block_rate": _rate(legitimate.ever_blocked),
                "legitimate_reviewed_devices": int(legitimate.ever_reviewed.sum()),
                "legitimate_blocked_devices": int(legitimate.ever_blocked.sum()),
            }
        )
    return rows


def _rate(series: pd.Series) -> float:
    return round(float(series.mean()), 4) if len(series) else 0.0


def merchant_category(kind: str) -> str:
    for category, kinds in MERCHANT_CATEGORY.items():
        if kind in kinds:
            return category
    return "unclassified"


def merchant_category_view(devices: pd.DataFrame) -> list[dict]:
    working = devices.copy()
    working["category"] = working.merchant_kind.map(merchant_category)
    rows = []
    for category, group in working.groupby("category"):
        attack = group.loc[group.label.eq(1)]
        legitimate = group.loc[group.label.eq(0)]
        rows.append(
            {
                "category": category,
                "kinds": sorted(set(group.merchant_kind)),
                "devices": int(len(group)),
                "attack_devices": int(len(attack)),
                "legitimate_devices": int(len(legitimate)),
                "attack_review_or_higher_recall": _rate(attack.ever_reviewed),
                "attack_block_recall": _rate(attack.ever_blocked),
                "legitimate_review_or_higher_rate": _rate(legitimate.ever_reviewed),
                "legitimate_block_rate": _rate(legitimate.ever_blocked),
            }
        )
    return rows


# --------------------------------------------------------------------------
# case analysis
# --------------------------------------------------------------------------


def _device_profile(frame: pd.DataFrame, risk: np.ndarray) -> pd.DataFrame:
    working = frame[
        ["device_id", "session_id", "scenario", "population", "merchant_kind"]
    ].copy()
    working["timestamp"] = pd.to_datetime(frame.timestamp, format="ISO8601")
    working["risk"] = np.asarray(risk, dtype=float)
    for name in (
        "requests_24h",
        "sessions_24h",
        "ip_changes_24h",
        "failure_ratio_24h",
        "decline_streak",
        "recent_failures_24h",
        "successful_checkouts",
        "distinct_card_last4_7d",
    ):
        working[name] = frame[name].to_numpy(dtype=float)
    grouped = working.groupby("device_id")
    profile = grouped.agg(
        scenario=("scenario", "first"),
        population=("population", "first"),
        merchant_kind=("merchant_kind", "first"),
        attempts=("risk", "size"),
        sessions=("session_id", "nunique"),
        max_risk=("risk", "max"),
        median_risk=("risk", "median"),
        max_requests_24h=("requests_24h", "max"),
        max_sessions_24h=("sessions_24h", "max"),
        max_ip_changes_24h=("ip_changes_24h", "max"),
        max_failure_ratio_24h=("failure_ratio_24h", "max"),
        max_decline_streak=("decline_streak", "max"),
        max_recent_failures_24h=("recent_failures_24h", "max"),
        max_successful_checkouts=("successful_checkouts", "max"),
        max_distinct_card_last4_7d=("distinct_card_last4_7d", "max"),
        first_seen=("timestamp", "min"),
        last_seen=("timestamp", "max"),
    )
    profile["span_hours"] = (
        profile.last_seen - profile.first_seen
    ).dt.total_seconds() / 3600.0
    return profile


def _summarise_profile(profile: pd.DataFrame, columns: tuple[str, ...]) -> dict:
    if profile.empty:
        return {"devices": 0}
    summary: dict = {
        "devices": int(len(profile)),
        "by_scenario": profile.scenario.value_counts().to_dict(),
        "by_merchant_kind": profile.merchant_kind.value_counts().to_dict(),
    }
    for name in columns:
        summary[name] = {
            "median": round(float(profile[name].median()), 4),
            "p90": round(float(profile[name].quantile(0.9)), 4),
            "max": round(float(profile[name].max()), 4),
        }
    return summary


PROFILE_COLUMNS = (
    "attempts",
    "sessions",
    "span_hours",
    "max_risk",
    "max_requests_24h",
    "max_sessions_24h",
    "max_ip_changes_24h",
    "max_failure_ratio_24h",
    "max_decline_streak",
    "max_successful_checkouts",
    "max_distinct_card_last4_7d",
)


def miss_analysis(frame: pd.DataFrame, risk: np.ndarray, devices: pd.DataFrame) -> dict:
    """What the system did not have on the attacks it never reviewed."""
    profile = _device_profile(frame, risk)
    missed = devices.loc[devices.label.eq(1) & ~devices.ever_reviewed]
    return _summarise_profile(
        profile.loc[profile.index.isin(missed.index)], PROFILE_COLUMNS
    )


def friction_analysis(
    frame: pd.DataFrame,
    risk: np.ndarray,
    devices: pd.DataFrame,
    replayed: pd.DataFrame,
) -> dict:
    """Why the policy believed a genuine customer was abusive."""
    profile = _device_profile(frame, risk)
    blocked = devices.loc[devices.label.eq(0) & devices.ever_blocked]
    summary = _summarise_profile(
        profile.loc[profile.index.isin(blocked.index)], PROFILE_COLUMNS
    )
    rows = replayed.loc[
        replayed.device_id.isin(blocked.index) & replayed.action.eq("block")
    ]
    summary["blocked_while_campaign_active"] = int(rows.campaign_active.sum())
    summary["blocked_attempts"] = int(len(rows))
    return summary
