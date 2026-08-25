"""FastAPI application backed exclusively by frozen, read-only artifacts."""

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, field_validator

from card_testing_sentinel.features.spec import MODEL_FEATURES
from card_testing_sentinel.policy.engine import decide_action
from card_testing_sentinel.rules.baseline import score_rules

ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str | None = None
    device_id: str | None = None
    features: dict[str, Any]

    @field_validator("features")
    @classmethod
    def exact_finite_features(cls, values: dict[str, Any]) -> dict[str, float]:
        if set(values) != set(MODEL_FEATURES):
            raise ValueError(
                "features must exactly match the frozen 26-feature contract"
            )
        clean = {}
        for name in MODEL_FEATURES:
            value = values[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"feature {name} must be numeric")
            if not np.isfinite(value):
                raise ValueError(f"feature {name} must be finite")
            clean[name] = float(value)
        return clean


class ArtifactRegistry:
    def __init__(self, root: Path = ROOT, config_path: Path | None = None):
        self.root = root
        self.config = yaml.safe_load(
            (config_path or root / "configs/app.yaml").read_text()
        )
        paths = {
            "model": root / "artifacts/models/hist_gradient_boosting.joblib",
            "policy": root / "artifacts/policy/frozen_policy.json",
            "final_metrics": root / "artifacts/metrics/final_test_metrics.json",
            "final_events": root
            / "artifacts/predictions/final_test_event_decisions.csv",
            "final_devices": root
            / "artifacts/predictions/final_test_device_summary.csv",
        }
        for name, path in paths.items():
            if (
                not path.is_file()
                or digest(path) != self.config["protected_hashes"][name]
            ):
                raise RuntimeError(f"artifact_verification_failed:{name}")
        self.model = joblib.load(paths["model"])
        self.policy = json.loads(paths["policy"].read_text())
        self.metrics = json.loads(paths["final_metrics"].read_text())
        self.events = pd.read_csv(paths["final_events"])
        self.devices = pd.read_csv(paths["final_devices"])
        self.training = yaml.safe_load((root / "configs/training.yaml").read_text())
        self.ready = True

    def evaluate(self, request: EvaluationRequest) -> dict:
        frame = pd.DataFrame(
            [[request.features[name] for name in MODEL_FEATURES]],
            columns=MODEL_FEATURES,
        )
        classes = list(self.model.classes_)
        if 1 not in classes:
            raise RuntimeError("attack_class_missing")
        probability = float(self.model.predict_proba(frame)[0, classes.index(1)])
        rules = score_rules(frame, self.training).iloc[0]
        comparisons = {}
        for method, result in self.policy["comparator_results"].items():
            action, reasons = decide_action(
                method, probability, int(rules["rule_score"]), result["thresholds"]
            )
            comparisons[method] = {
                "action": action,
                "reason_codes": [reasons] if reasons else [],
            }
        champion = self.policy["selected_policy_method"]
        return {
            "event_id": request.event_id,
            "device_id": request.device_id,
            "advisory_model_risk_probability": probability,
            "rule_score": int(rules["rule_score"]),
            "rule_reason_codes": rules["reason_codes"].split("|")
            if rules["reason_codes"]
            else [],
            "selected_policy_method": champion,
            "selected_action": comparisons[champion]["action"],
            "selected_action_reason_codes": comparisons[champion]["reason_codes"],
            "comparison_only": {k: v for k, v in comparisons.items() if k != champion},
            "decision_moment": "post_authorization",
            "action_effect": "next_attempt",
            "threshold_selected_from_request": False,
        }


def create_app(registry: ArtifactRegistry | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.registry = registry or ArtifactRegistry()
            app.state.readiness_error = None
        except Exception:
            app.state.registry = None
            app.state.readiness_error = "artifact_verification_failed"
        yield

    app = FastAPI(title="Card-Testing Sentinel", version="0.5.0", lifespan=lifespan)
    app.mount(
        "/static",
        StaticFiles(directory=ROOT / "src/card_testing_sentinel/static"),
        name="static",
    )

    def ready(request: Request) -> ArtifactRegistry:
        if request.app.state.registry is None:
            raise HTTPException(503, {"code": "artifact_not_ready"})
        return request.app.state.registry

    @app.get("/health/live")
    def live():
        return {
            "status": "alive",
            "application_name": "Card-Testing Sentinel",
            "application_version": "0.5.0",
        }

    @app.get("/health/ready")
    def readiness(request: Request):
        r = ready(request)
        return {
            "status": "ready",
            "champion_method": r.policy["selected_policy_method"],
            "model_hash_prefix": r.config["protected_hashes"]["model"][:12],
            "policy_hash_prefix": r.config["protected_hashes"]["policy"][:12],
            "dataset_version": r.policy["dataset_version"],
            "scoring_semantics_version": r.policy["action_logic_identifier"],
        }

    @app.get("/api/v1/system")
    def system(request: Request):
        r = ready(request)
        return {
            "project_name": r.config["app_name"],
            "version": r.config["app_version"],
            "synthetic_buildathon_prototype": True,
            "champion_method": "rules_only",
            "hgb_role": "advisory risk scorer",
            "decision_moment": "post_authorization",
            "block_meaning": "block the next attempt",
            "feature_count": 26,
            "feature_contract_hash_prefix": r.policy["feature_hash"][:12],
            "no_threshold_editing": True,
            "final_test_immutable": True,
        }

    @app.post("/api/v1/evaluate")
    def evaluate(payload: EvaluationRequest, request: Request):
        return ready(request).evaluate(payload)

    @app.get("/api/v1/metrics")
    def metrics(request: Request):
        return ready(request).metrics

    @app.get("/api/v1/devices")
    def devices(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=50),
        population: str | None = None,
        attack_subtype: str | None = None,
        scenario_exposure: str | None = None,
        detected: bool | None = None,
    ):
        r = ready(request)
        data = r.devices.copy()
        if population:
            data = data[data.population.eq(population)]
        if attack_subtype:
            data = data[data.attack_subtype.eq(attack_subtype)]
        if scenario_exposure:
            data = data[
                data.scenario_exposures.fillna("")
                .str.split("|")
                .apply(lambda values: scenario_exposure in values)
            ]
        if detected is not None:
            data = data[data.ever_blocked.eq(detected)]
        data = data.sort_values("device_id")
        start = (page - 1) * page_size
        fields = [
            "device_id",
            "population",
            "attack_subtype",
            "scenario_exposures",
            "authorization_count",
            "first_block_position",
            "ever_blocked",
        ]
        page_data = data.iloc[start : start + page_size][fields].astype(object)
        return {
            "total_devices": len(data),
            "page": page,
            "items": page_data.where(pd.notna(page_data), None).to_dict("records"),
        }

    @app.get("/api/v1/devices/{device_id}/timeline")
    def timeline(device_id: str, request: Request):
        r = ready(request)
        rows = r.events[r.events.device_id.eq(device_id)].sort_values(
            "authorization_position"
        )
        if rows.empty:
            raise HTTPException(404, {"code": "synthetic_device_not_found"})
        first = pd.to_datetime(rows.timestamp.iloc[0])
        cards = {
            token: f"Card {i + 1}"
            for i, token in enumerate(rows.card_token.drop_duplicates())
        }
        items = [
            {
                "authorization_position": int(row.authorization_position),
                "relative_seconds": (
                    pd.to_datetime(row.timestamp) - first
                ).total_seconds(),
                "advisory_model_risk_probability": float(row.risk_score),
                "rule_score": int(row.rule_score),
                "rule_reason_codes": str(row.fixed_rule_reason_codes).split("|")
                if pd.notna(row.fixed_rule_reason_codes)
                else [],
                "selected_action": row.rules_only_action,
                "comparison_actions": {
                    "ml_only": row.ml_only_action,
                    "combined": row.combined_action,
                },
                "is_first_block": bool(row.champion_is_first_block),
                "potentially_prevented": bool(row.champion_potentially_prevented),
                "display_card": cards[row.card_token],
            }
            for _, row in rows.iterrows()
        ]
        summary = r.devices[r.devices.device_id.eq(device_id)].iloc[0]

        def native(value):
            if pd.isna(value):
                return None
            return value.item() if hasattr(value, "item") else value

        return {
            "device_id": device_id,
            "summary": {
                k: native(summary[k])
                for k in [
                    "ever_blocked",
                    "first_block_position",
                    "attempts_processed_through_detection",
                    "distinct_cards_before_detection_attempt",
                    "distinct_cards_processed_through_detection",
                    "seconds_to_detection",
                    "remaining_recorded_attempts_after_detection",
                ]
            },
            "events": items,
            "disclaimer": (
                "Potentially preventable attempts are an offline upper-bound estimate."
            ),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return (ROOT / "src/card_testing_sentinel/templates/dashboard.html").read_text()

    return app
