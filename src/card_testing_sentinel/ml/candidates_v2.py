"""The Model v2 candidate set.

Three families, deliberately: logistic regression over a wide regularisation
grid, the same with a handful of NAMED interaction terms, and gradient
boosting. Random forests, XGBoost, LightGBM and anything deep are excluded --
HistGradientBoosting already lost to plain LR on v1 (PR-AUC 0.587 vs 0.657),
so more capacity of the same shape is not the open question.

Every candidate carries its own feature list, which is what lets the ablation
study refit the *selected* configuration on a subset without a second code
path.
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

from card_testing_sentinel.features.specification_v2 import MODEL_FEATURES_V2

LOGISTIC_FAMILIES = ("logistic_regression", "logistic_interactions")


def interaction_name(left: str, right: str) -> str:
    return f"{left}__x__{right}"


def add_interactions(frame: pd.DataFrame, pairs: tuple) -> pd.DataFrame:
    """Append named product terms.

    A module-level function so the fitted pipeline stays picklable, and a
    handful of named pairs rather than a polynomial expansion so the
    coefficient table stays readable.
    """
    working = frame.copy()
    for left, right in pairs:
        working[interaction_name(left, right)] = working[left].to_numpy(
            dtype=float
        ) * working[right].to_numpy(dtype=float)
    return working


@dataclass(frozen=True)
class CandidateV2:
    identifier: str
    family: str
    parameters: dict[str, Any]
    features: tuple[str, ...] = MODEL_FEATURES_V2
    interactions: tuple[tuple[str, str], ...] = ()

    def with_features(self, features: tuple[str, ...], suffix: str) -> CandidateV2:
        kept = tuple(name for name in features)
        pairs = tuple(pair for pair in self.interactions if set(pair) <= set(kept))
        return CandidateV2(
            identifier=f"{self.identifier}__{suffix}",
            family=self.family,
            parameters=dict(self.parameters),
            features=kept,
            interactions=pairs,
        )


def candidate_grid_v2(config: dict) -> list[CandidateV2]:
    grids = config["training"]["candidate_grids"]
    pairs = tuple(tuple(pair) for pair in config["interactions"])
    candidates: list[CandidateV2] = []

    logistic = grids["logistic_regression"]
    for value in logistic["C"]:
        candidates.append(
            CandidateV2(
                identifier=f"logistic_C{value}",
                family="logistic_regression",
                parameters={"C": float(value), "max_iter": int(logistic["max_iter"])},
            )
        )
    interacting = grids["logistic_interactions"]
    for value in interacting["C"]:
        candidates.append(
            CandidateV2(
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
            CandidateV2(
                identifier=f"hist_gb_{index + 1}",
                family="hist_gradient_boosting",
                parameters=dict(spec),
            )
        )
    return candidates


def build_model_v2(candidate: CandidateV2, seed: int):
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


def _inputs(candidate: CandidateV2, frame: pd.DataFrame):
    values = frame.loc[:, list(candidate.features)]
    if candidate.family in LOGISTIC_FAMILIES:
        return values
    return values.to_numpy(dtype=float)


def fit_model_v2(model, candidate: CandidateV2, frame, labels, weights):
    key = (
        "classifier__sample_weight"
        if candidate.family in LOGISTIC_FAMILIES
        else "sample_weight"
    )
    model.fit(_inputs(candidate, frame), labels, **{key: weights})
    return model


def predict_v2(model, candidate: CandidateV2, frame) -> np.ndarray:
    return np.asarray(model.predict_proba(_inputs(candidate, frame))[:, 1], dtype=float)


def fitted_feature_names(candidate: CandidateV2) -> list[str]:
    """Column order the fitted linear model sees, interactions included."""
    names = list(candidate.features)
    names.extend(
        interaction_name(left, right) for left, right in candidate.interactions
    )
    return names
