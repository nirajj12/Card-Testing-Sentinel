"""Select Policy v2 on Dataset v3 validation only.

    python pipelines/select_policy_v2.py

Replays the frozen Model v2 validation scores through a compact predefined
candidate grid, keeps only candidates inside the friction budget declared
before scoring, ranks the survivors by a documented objective, and writes the
frozen policy artifact.

Model v2 is not retrained. Policy v1 is untouched. No blind data is read.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
import yaml

from card_testing_sentinel.features.specification_v2 import MODEL_FEATURES_V2
from card_testing_sentinel.ml.evaluation_v2 import threshold_table
from card_testing_sentinel.ml.policy_search_v2 import (
    assert_engine_parity,
    candidate_configs_v2,
    candidate_label,
    cost_table,
    decide_vector,
    device_view,
    evaluate_candidates_v2,
    evidence_gate_value,
    merchant_view,
    precompute,
    scenario_view,
    segment_view,
    select,
    summarise,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development_v3/features_v2.csv"
MODEL_DIR = ROOT / "artifacts/model_v2"
POLICY_DIR = ROOT / "artifacts/policy_v2"
OUT = ROOT / "artifacts/evaluation"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_resolved_policy_config(path: Path, selected: dict) -> None:
    """Write selected values into the policy block, preserving commentary.

    This deliberately replaces existing scalar values as well as ``null``.
    The previous implementation only replaced null placeholders, so a rerun
    after a different selection could hash a stale config.
    """
    lines = path.read_text().splitlines(keepends=True)
    in_policy = False
    replaced: set[str] = set()
    for index, line in enumerate(lines):
        if line == "policy:\n":
            in_policy = True
            continue
        if in_policy and line and not line.startswith((" ", "#", "\n")):
            in_policy = False
        if not in_policy:
            continue
        match = re.match(r"^(  ([a-z0-9_]+):)[^#\n]*(.*\n?)$", line)
        if not match or match.group(2) not in selected:
            continue
        key = match.group(2)
        scalar = json.dumps(selected[key])
        lines[index] = f"{match.group(1)} {scalar}{match.group(3)}"
        replaced.add(key)
    expected = set(selected)
    if replaced != expected:
        missing = sorted(expected - replaced)
        raise RuntimeError(f"policy config is missing selected keys: {missing}")
    path.write_text("".join(lines))
    resolved = yaml.safe_load(path.read_text())["policy"]
    for key, value in selected.items():
        if resolved.get(key) != value:
            raise RuntimeError(f"policy config did not resolve {key}")


def decision_metrics(frame: pd.DataFrame, ranks) -> dict:
    """Device outcomes plus benchmark-conditional attempt precision/volume."""
    ranks = pd.Series(ranks, index=frame.index)
    reviewed = ranks.ge(1)
    labels = frame.label.astype(int)
    summary = summarise(device_view(frame, ranks.to_numpy(dtype=int)))
    summary.update(
        {
            "review_or_higher_attempts": int(reviewed.sum()),
            "review_or_higher_attempt_rate": round(float(reviewed.mean()), 4),
            "benchmark_attempt_precision": (
                round(float(labels.loc[reviewed].mean()), 4) if reviewed.any() else None
            ),
        }
    )
    return summary


if __name__ == "__main__":
    config = yaml.safe_load((ROOT / "configs/policy_v2.yaml").read_text())
    search, constraints = config["policy_search"], config["policy_constraints"]
    metadata = json.loads((MODEL_DIR / "metadata.json").read_text())
    artifact = joblib.load(MODEL_DIR / "risk_model_v2.joblib")

    frame = pd.read_csv(DATA)
    validation = frame.loc[frame.split.eq("validation")].reset_index(drop=True)
    if validation.empty:
        raise RuntimeError("validation split is empty")
    # `campaign_active` is a merchant fact carried on the request, not a
    # model feature -- the policy is told it explicitly.
    raw = pd.read_csv(
        ROOT / "data/generated/development_v3/raw_events.csv",
        dtype={"card_last4": "string", "customer_id": "string"},
    )
    requests = raw.loc[
        raw.event_type.eq("authorization_request"), ["request_id", "campaign_active"]
    ]
    validation = validation.merge(requests, on="request_id", how="left")
    validation["campaign_active"] = (
        validation.campaign_active.astype("boolean").fillna(False).astype(bool)
    )

    risk = artifact.score_frame(validation)
    precomputed = precompute(validation, MODEL_FEATURES_V2)

    base = {
        "block_ttl_seconds": int(search["block_ttl_candidates"][-1]),
        "degraded_review_rule_score": config["policy"]["degraded_review_rule_score"],
        "degraded_block_rule_score": config["policy"]["degraded_block_rule_score"],
    }
    candidates = candidate_configs_v2(search, base)
    table, scenario_tables = evaluate_candidates_v2(
        validation, risk, candidates, constraints, precomputed
    )
    chosen = select(table)
    chosen_config = next(
        c for c in candidates if candidate_label(c) == chosen.candidate
    )

    # The vectorised search must agree with the real engine, row for row.
    ranks = assert_engine_parity(
        validation, risk, chosen_config, precomputed, MODEL_FEATURES_V2
    )
    devices = device_view(validation, ranks)
    summary = summarise(devices)
    scenarios = scenario_view(devices)
    merchants = merchant_view(devices)
    segments = segment_view(devices)
    gate = evidence_gate_value(validation, risk, chosen_config, precomputed)

    # Model-only behaviour at the same cuts, so we can see whether the policy
    # improves product behaviour or merely hides model errors.
    model_only = threshold_table(
        validation,
        risk,
        [chosen_config["review_threshold"], chosen_config["block_threshold"]],
    )

    # The v1 evidence vocabulary at the SAME thresholds, as the like-for-like
    # comparison the phase asks for.
    v1_like_config = {**chosen_config, "evidence_set": "v1_like"}
    v1_like_devices = device_view(
        validation,
        decide_vector(
            risk,
            validation.campaign_active.to_numpy(dtype=bool),
            precomputed["evidence"]["v1_like"],
            precomputed["trust"][chosen_config["trust_suppression"]],
            v1_like_config,
        ),
    )
    v1_scenarios = scenario_view(v1_like_devices)

    campaign = validation.campaign_active.to_numpy(dtype=bool)
    review_sweep_rows = []
    for review_threshold in search["reporting_review_thresholds"]:
        sweep_config = {**chosen_config, "review_threshold": float(review_threshold)}
        sweep_ranks = decide_vector(
            risk,
            campaign,
            precomputed["evidence"][sweep_config["evidence_set"]],
            precomputed["trust"][sweep_config["trust_suppression"]],
            sweep_config,
        )
        review_sweep_rows.append(
            {
                "review_threshold": float(review_threshold),
                **decision_metrics(validation, sweep_ranks),
            }
        )
    review_sweep = pd.DataFrame(review_sweep_rows)

    block_sweep_rows = []
    for block_threshold in search["block_thresholds"]:
        sweep_config = {**chosen_config, "block_threshold": float(block_threshold)}
        sweep_ranks = decide_vector(
            risk,
            campaign,
            precomputed["evidence"][sweep_config["evidence_set"]],
            precomputed["trust"][sweep_config["trust_suppression"]],
            sweep_config,
        )
        block_sweep_rows.append(
            {
                "block_threshold": float(block_threshold),
                **decision_metrics(validation, sweep_ranks),
                **evidence_gate_value(validation, risk, sweep_config, precomputed),
            }
        )
    block_sweep = pd.DataFrame(block_sweep_rows)

    adjusted_config = {
        **chosen_config,
        "campaign_review_increment": float(search["campaign_increments"][1][0]),
        "campaign_block_increment": float(search["campaign_increments"][1][1]),
    }
    campaign_comparison = {}
    for name, comparison_config in (
        ("no_adjustment", chosen_config),
        ("small_adjustment", adjusted_config),
    ):
        comparison_ranks = decide_vector(
            risk,
            campaign,
            precomputed["evidence"][comparison_config["evidence_set"]],
            precomputed["trust"][comparison_config["trust_suppression"]],
            comparison_config,
        )
        campaign_comparison[name] = decision_metrics(validation, comparison_ranks)

    evidence_comparison = {
        scenario: {
            "v1_like_block_rate": float(v1_scenarios.loc[scenario, "block_rate"]),
            "v2_full_block_rate": float(scenarios.loc[scenario, "block_rate"]),
            "block_rate_change": round(
                float(
                    scenarios.loc[scenario, "block_rate"]
                    - v1_scenarios.loc[scenario, "block_rate"]
                ),
                4,
            ),
        }
        for scenario in (
            "patient_tester_weeks",
            "sparse_multiday_tester",
            "cross_device_campaign",
        )
    }

    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    table.sort_values(
        ["eligible", "attack_review_or_higher_recall"], ascending=[False, False]
    ).to_csv(OUT / "policy_v2_candidates.csv", index=False)
    scenarios.to_csv(OUT / "policy_v2_scenarios.csv")
    merchants.to_csv(OUT / "policy_v2_merchants.csv", index=False)
    segments.to_csv(OUT / "policy_v2_segments.csv", index=False)
    v1_scenarios.to_csv(OUT / "policy_v2_v1_evidence.csv")
    review_sweep.to_csv(OUT / "policy_v2_review_thresholds.csv", index=False)
    block_sweep.to_csv(OUT / "policy_v2_block_thresholds.csv", index=False)

    selected = {
        "version": config["policy"]["version"],
        "family": chosen_config["family"],
        "review_threshold": float(chosen_config["review_threshold"]),
        "block_threshold": float(chosen_config["block_threshold"]),
        "block_evidence": int(chosen_config["block_evidence"]),
        "evidence_set": chosen_config["evidence_set"],
        "trust_suppression": chosen_config["trust_suppression"],
        "block_ttl_seconds": int(chosen_config["block_ttl_seconds"]),
        "campaign_review_increment": float(chosen_config["campaign_review_increment"]),
        "campaign_block_increment": float(chosen_config["campaign_block_increment"]),
        "degraded_review_rule_score": int(base["degraded_review_rule_score"]),
        "degraded_block_rule_score": int(base["degraded_block_rule_score"]),
    }
    # Resolve the config on disk BEFORE hashing it, so `policy_config_sha256`
    # describes the file a reader will actually find.
    policy_config_path = ROOT / "configs/policy_v2.yaml"
    write_resolved_policy_config(policy_config_path, selected)
    policy_config_sha256 = sha256(policy_config_path)

    record = {
        **selected,
        "status": "validation_selected_v2",
        "selected_on": "Dataset v3 validation split only",
        "policy_stage": "validation_selected",
        "model_version": metadata["model_version"],
        "model_sha256": metadata["model_sha256"],
        "model_metadata_sha256": sha256(MODEL_DIR / "metadata.json"),
        "feature_contract_sha256": metadata["feature_contract_sha256"],
        "policy_config_sha256": policy_config_sha256,
        "features_sha256": sha256(DATA),
        "candidates_evaluated": int(len(table)),
        "candidates_eligible": int(table.eligible.sum()),
        "constraints": constraints,
        "ranking": (
            "constraint-first, then: attack review+ recall, attack block "
            "recall, earlier detection, lower legitimate review friction, "
            "broader evidence vocabulary, stronger evidence requirement"
        ),
        "scenario_budget_revision": {
            "timing": "after the first zero-eligible search and before policy freeze",
            "original": (
                "nine hand-authored family caps, including "
                "shared_network_customer block <= 0.01"
            ),
            "problem": (
                "small enriched cohorts made those rates resolve to one or two "
                "devices and treated sampling granularity as a safety result"
            ),
            "replacement": (
                "uniform 6x aggregate block and 5x aggregate review stress "
                "ceilings, each floored at two devices; aggregate caps unchanged"
            ),
            "interpretation": (
                "scenario ceilings are catastrophic-concentration guardrails, "
                "not statistical confidence bounds or family safety claims"
            ),
        },
        "review_meaning": (
            "a decision state in this prototype; a merchant could map it to "
            "step-up verification, rate limiting, a delayed retry or a manual "
            "queue. Sentinel issues no OTP, 3DS or issuer action."
        ),
        "block_meaning": (
            "temporary. No Razorpay order is created for this attempt; after "
            "block_expires_at a later request is scored from current history. "
            "Nothing is permanently labelled fraudulent."
        ),
        "validation_metrics": summary,
        "attack_scenario_detection": {
            name: {
                "devices": int(row.devices),
                "review_or_higher_rate": float(row.review_or_higher_rate),
                "block_rate": float(row.block_rate),
                "median_first_review": (
                    None
                    if pd.isna(row.median_first_review)
                    else float(row.median_first_review)
                ),
            }
            for name, row in scenarios.loc[scenarios.population.eq("attack")].iterrows()
        },
        "legitimate_scenario_friction": {
            name: {
                "devices": int(row.devices),
                "review_or_higher_rate": float(row.review_or_higher_rate),
                "block_rate": float(row.block_rate),
            }
            for name, row in scenarios.loc[
                scenarios.population.eq("legitimate")
            ].iterrows()
        },
        "merchant_friction": json.loads(merchants.to_json(orient="records")),
        "customer_id_segments": json.loads(segments.to_json(orient="records")),
        "evidence_gate_value": gate,
        "evidence_gate_diagnosis": (
            "Dataset v3 validation does not exercise the selected gate: every "
            "attempt at score >= 0.90 already has at least two v2_full evidence "
            "signals. This demonstrates zero incremental protection here; it "
            "does not establish that the architecture has no value under shift."
        ),
        "evidence_comparison": evidence_comparison,
        "campaign_adjustment_comparison": campaign_comparison,
        "campaign_adjustment_decision": (
            "not retained: the small tolerance does not dominate the "
            "campaign-free candidate across attack recall, attack blocking, "
            "legitimate review friction, and legitimate blocking"
        ),
        "review_threshold_sweep": json.loads(review_sweep.to_json(orient="records")),
        "block_threshold_sweep": json.loads(block_sweep.to_json(orient="records")),
        "model_only_at_same_thresholds": json.loads(
            model_only.to_json(orient="records")
        ),
        "cost_table": cost_table(devices, config["costs"]),
        "ttl_candidates": list(search["block_ttl_candidates"]),
        "ttl_note": (
            "A block never suppresses a later attempt in this measurement, so "
            "TTL changes no replay metric. It is chosen for explainability: "
            "long enough to break an automated run's cadence, short enough "
            "that a wrongly blocked customer can retry inside one shopping "
            "session. A prototype choice, not a Razorpay recommendation."
        ),
        "created_utc": datetime.now(UTC).isoformat(),
        "blind_evaluated": False,
        "blind_v2_generated": False,
    }
    policy_artifact_path = POLICY_DIR / "operational_policy_v2.json"
    policy_artifact_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n"
    )
    (POLICY_DIR / "operational_policy_v2.sha256").write_text(
        f"{sha256(policy_artifact_path)}  {policy_artifact_path.name}\n"
    )

    # Independent post-write assertions: the bytes on disk, not an in-memory
    # template, are the source of truth for both bindings.
    frozen = json.loads(policy_artifact_path.read_text())
    if frozen["policy_config_sha256"] != sha256(policy_config_path):
        raise RuntimeError("final policy config hash verification failed")
    recorded_artifact_hash = (
        (POLICY_DIR / "operational_policy_v2.sha256").read_text().split()[0]
    )
    if recorded_artifact_hash != sha256(policy_artifact_path):
        raise RuntimeError("final policy artifact hash verification failed")

    print(json.dumps(selected, indent=2))
    print("\n--- validation metrics ---")
    print(json.dumps(summary, indent=2))
    print("\n--- evidence gate ---")
    print(
        json.dumps({k: v for k, v in gate.items() if not isinstance(v, dict)}, indent=2)
    )
    print(f"\ncandidates {len(table)} evaluated, {int(table.eligible.sum())} eligible")
