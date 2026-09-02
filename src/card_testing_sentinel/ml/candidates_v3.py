"""The Model v3 candidate set.

Three candidate families:
1. Logistic regression (regularized L2 Ridge)
2. Logistic regression with explicit domain interaction terms
3. Histogram-based Gradient Boosting (HistGradientBoostingClassifier)

Supports feature subsets for the Phase 2 ablation studies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from card_testing_sentinel.features.specification_v3 import MODEL_FEATURES_V3

LOGISTIC_FAMILIES = ("logistic_regression", "logistic_interactions")


def interaction_name(left: str, right: str) -> str:
    return f"{left}__x__{right}"


def add_interactions(frame: pd.DataFrame, pairs: tuple) -> pd.DataFrame:
    working = frame.copy()
    for left, right in pairs:
        if left in working.columns and right in working.columns:
            working[interaction_name(left, right)] = working[left].to_numpy(
                dtype=float
            ) * working[right].to_numpy(dtype=float)
    return working


@dataclass(frozen=True)
class CandidateV3:
    identifier: str
    family: str
    parameters: dict[str, Any]
    features: tuple[str, ...] = MODEL_FEATURES_V3
    interactions: tuple[tuple[str, str], ...] = ()

    def with_features(self, features: tuple[str, ...], suffix: str) -> CandidateV3:
        kept = tuple(name for name in features)
        pairs = tuple(pair for pair in self.interactions if set(pair) <= set(kept))
        return CandidateV3(
            identifier=f"{self.identifier}__{suffix}",
            family=self.family,
            parameters=dict(self.parameters),
            features=kept,
            interactions=pairs,
        )


def candidate_grid_v3(config: dict) -> list[CandidateV3]:
    grids = config["training"]["candidate_grids"]
    pairs = tuple(tuple(pair) for pair in config.get("interactions", []))
    candidates: list[CandidateV3] = []

    logistic = grids["logistic_regression"]
    for value in logistic["C"]:
        candidates.append(
            CandidateV3(
                identifier=f"logistic_C{value}",
                family="logistic_regression",
                parameters={"C": float(value), "max_iter": int(logistic["max_iter"])},
            )
        )
    interacting = grids["logistic_interactions"]
    for value in interacting["C"]:
        candidates.append(
            CandidateV3(
                identifier=f"logistic_interactions_C{value}",
                family="logistic_interactions",
                parameters={
                    "C": float(value),
                    "max_iter": int(interacting["max_iter"]),
                },
                interactions=pairs,
            )
        )
    for index, spec in enumerate(grids["hist_gradient_boosting"]):
        candidates.append(
            CandidateV3(
                identifier=f"hist_gb_{index + 1}",
                family="hist_gradient_boosting",
                parameters=dict(spec),
            )
        )
    return candidates


def build_model_v3(candidate: CandidateV3, seed: int):
    if candidate.family in LOGISTIC_FAMILIES:
        steps = []
        if candidate.interactions:
            steps.append(
                (
                    "interactions",
                    FunctionTransformer(
                        add_interactions,
                        kw_args={"pairs": candidate.interactions},
                        validate=False,
                    ),
                )
            )
        steps.extend(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(random_state=seed, **candidate.parameters),
                ),
            ]
        )
        return Pipeline(steps)
    if candidate.family == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=seed, **candidate.parameters)
    raise ValueError(f"unknown candidate family: {candidate.family}")


def _inputs(candidate: CandidateV3, frame: pd.DataFrame):
    values = frame.loc[:, list(candidate.features)]
    if candidate.family in LOGISTIC_FAMILIES:
        return values
    # HistGradientBoosting handles NaNs natively or with median imputation
    arr = values.to_numpy(dtype=float)
    return np.nan_to_num(arr, nan=0.0)


def fit_model_v3(model, candidate: CandidateV3, frame, labels, weights=None):
    inputs = _inputs(candidate, frame)
    if weights is not None:
        key = (
            "classifier__sample_weight"
            if candidate.family in LOGISTIC_FAMILIES
            else "sample_weight"
        )
        model.fit(inputs, labels, **{key: weights})
    else:
        model.fit(inputs, labels)
    return model


def predict_v3(model, candidate: CandidateV3, frame) -> np.ndarray:
    return np.asarray(model.predict_proba(_inputs(candidate, frame))[:, 1], dtype=float)


def fitted_feature_names_v3(candidate: CandidateV3) -> list[str]:
    names = list(candidate.features)
    names.extend(
        interaction_name(left, right) for left, right in candidate.interactions
    )
    return names
