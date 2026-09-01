"""Select the operating point on VALIDATION and freeze the policy artifact.

    python pipelines/select_policy.py

Replays the frozen model's validation scores through the candidate policy
grid declared in configs/policy.yaml, applies the declared friction budget,
and writes artifacts/policy/operational_policy.json plus the evaluation
tables. The model is never refitted and no blind data is read or created.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
import yaml

from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.ml.policy_search import (
    candidate_configs,
    cost_table,
    device_view,
    evaluate_candidates,
    merchant_view,
    replay,
    scenario_view,
    select,
    summarise,
)
from card_testing_sentinel.policy.engine import RiskPolicy

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development"
MODEL_DIR = ROOT / "artifacts/model"
POLICY_DIR = ROOT / "artifacts/policy"
OUT = ROOT / "artifacts/evaluation"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_validation() -> pd.DataFrame:
    features = pd.read_csv(DATA / "features.csv")
    raw = pd.read_csv(DATA / "raw_events.csv", dtype={"card_last4": "string"})
    campaign = raw.loc[
        raw.event_type.eq("authorization_request"), ["request_id", "campaign_active"]
    ]
    merged = features.merge(campaign, on="request_id", how="left")
    merged["campaign_active"] = (
        merged.campaign_active.astype("boolean").fillna(False).astype(bool)
    )
    validation = merged.loc[merged.split.eq("validation")].reset_index(drop=True)
    if validation.empty:
        raise RuntimeError("validation split is empty")
    return validation


if __name__ == "__main__":
    config = yaml.safe_load((ROOT / "configs/policy.yaml").read_text())
    search, constraints = config["policy_search"], config["policy_constraints"]
    metadata = json.loads((MODEL_DIR / "metadata.json").read_text())
    artifact = joblib.load(MODEL_DIR / "risk_model.joblib")

    validation = load_validation()
    risk = artifact.score_frame(validation.loc[:, list(MODEL_FEATURES)])

    base = {
        "block_ttl_seconds": config["policy"]["block_ttl_seconds"],
        "persistence_window_hours": config["policy"]["persistence_window_hours"],
        "history_cap": config["policy"]["history_cap"],
        "degraded_review_rule_score": config["policy"]["degraded_review_rule_score"],
        "degraded_block_rule_score": config["policy"]["degraded_block_rule_score"],
    }
    candidates = candidate_configs(search, base)
    table, scenario_tables = evaluate_candidates(
        validation, risk, candidates, constraints
    )
    chosen = select(table)

    OUT.mkdir(parents=True, exist_ok=True)
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    table.sort_values(
        ["eligible", "attack_review_or_higher_recall"], ascending=[False, False]
    ).to_csv(OUT / "policy_candidates.csv", index=False)

    selected = {
        "family": chosen.family,
        "review_threshold": float(chosen.review_threshold),
        "block_threshold": float(chosen.block_threshold),
        "block_evidence": int(chosen.block_evidence),
        "block_elevated_count": int(chosen.block_elevated_count),
        "campaign_review_increment": float(chosen.campaign_review_increment),
        "campaign_block_increment": float(chosen.campaign_block_increment),
        **base,
    }
    policy = RiskPolicy(selected)
    devices = device_view(replay(validation, risk, policy))
    summary = summarise(devices)
    scenarios = scenario_view(devices)
    merchants = merchant_view(devices)

    scenarios.to_csv(OUT / "policy_scenario_metrics.csv")
    merchants.to_csv(OUT / "policy_merchant_metrics.csv", index=False)

    # campaign-aware vs campaign-agnostic, on the otherwise identical winner
    campaign_rows = []
    for label, increments in (
        ("campaign_agnostic", (0.0, 0.0)),
        ("campaign_aware_light", (0.05, 0.02)),
        ("campaign_aware_strong", (0.10, 0.05)),
    ):
        variant = {
            **selected,
            "campaign_review_increment": increments[0],
            "campaign_block_increment": increments[1],
        }
        variant_devices = device_view(replay(validation, risk, RiskPolicy(variant)))
        variant_scenarios = scenario_view(variant_devices)
        campaign_rows.append(
            {
                "variant": label,
                "review_increment": increments[0],
                "block_increment": increments[1],
                **summarise(variant_devices),
                "flash_sale_customer_review_rate": float(
                    variant_scenarios.loc[
                        "flash_sale_customer", "review_or_higher_rate"
                    ]
                ),
                "flash_sale_customer_block_rate": float(
                    variant_scenarios.loc["flash_sale_customer", "block_rate"]
                ),
            }
        )

    validation_metrics = {
        "status": "validation_selected",
        "blind_evaluated": False,
        "selected_policy": selected,
        "candidates_evaluated": int(len(table)),
        "candidates_eligible": int(table.eligible.sum()),
        "constraints": constraints,
        "ranking": search["ranking"],
        "aggregate": summary,
        "cost_table": cost_table(devices, config["policy_costs"]),
        "campaign_comparison": campaign_rows,
        "validation_devices": int(len(devices)),
        "validation_rows": int(len(validation)),
        "prevalence_note": (
            "benchmark prevalence is enriched; rates are per-population and "
            "per-scenario, which is what makes them comparable"
        ),
    }
    (OUT / "policy_validation_metrics.json").write_text(
        json.dumps(validation_metrics, indent=2, sort_keys=True, default=str) + "\n"
    )

    operational = {
        "policy_version": config["policy"]["version"],
        "status": "validation_selected",
        "blind_evaluated": False,
        "selected_on": "validation split only",
        "policy_family": chosen.family,
        **selected,
        "review_meaning": (
            "a decision state in this prototype; a production merchant could map "
            "it to step-up verification, rate limiting, a delayed retry or a "
            "manual queue. None of those are implemented here."
        ),
        "block_meaning": (
            "temporary. No Razorpay order is created for this attempt; after "
            "block_expires_at a later request is scored from current history. "
            "Nothing is permanently labelled fraudulent."
        ),
        "constraints": constraints,
        "ranking": search["ranking"],
        "validation_metrics": summary,
        "legitimate_scenario_friction": scenarios.loc[
            scenarios.population.eq("legitimate"),
            ["devices", "review_or_higher_rate", "block_rate"],
        ].to_dict("index"),
        "attack_scenario_detection": scenarios.loc[
            scenarios.population.eq("attack"),
            ["devices", "review_or_higher_rate", "block_rate", "median_first_review"],
        ].to_dict("index"),
        "merchant_friction": merchants.to_dict("records"),
        "feature_contract_sha256": MODEL_FEATURES_SHA256,
        "model_sha256": _sha256(MODEL_DIR / "risk_model.joblib"),
        "model_metadata_sha256": _sha256(MODEL_DIR / "metadata.json"),
        "model_stage": metadata["status"],
        "training_config_sha256": metadata["training_config_sha256"],
        "dataset_config_sha256": metadata["dataset_config_sha256"],
        "policy_config_sha256": _sha256(ROOT / "configs/policy.yaml"),
        "created_utc": datetime.now(UTC).isoformat(),
    }
    (POLICY_DIR / "operational_policy.json").write_text(
        json.dumps(operational, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                "selected": selected,
                "candidates_evaluated": len(table),
                "candidates_eligible": int(table.eligible.sum()),
                "aggregate": summary,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
