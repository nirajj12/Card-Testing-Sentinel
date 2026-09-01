"""The candidate model set: logistic regression and gradient boosting.

Deliberately two families and a handful of settings each. The question this
phase answers is "does ML beat rules and counters", not "which of forty
hyperparameter combinations wins by a decimal" -- a large search on a
30k-row synthetic benchmark would mostly be fitting the search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from card_testing_sentinel.features.specification import MODEL_FEATURES


@dataclass(frozen=True)
class Candidate:
    identifier: str
    family: str
    parameters: dict[str, Any]


def candidate_grid(config: dict) -> list[Candidate]:
    grids = config["candidate_grids"]
    candidates: list[Candidate] = []
    logistic = grids["logistic_regression"]
    for value in logistic["C"]:
        candidates.append(
            Candidate(
                identifier=f"logistic_C{value}",
                family="logistic_regression",
                parameters={"C": float(value), "max_iter": int(logistic["max_iter"])},
            )
        )
    for index, spec in enumerate(grids["hist_gradient_boosting"]):
        candidates.append(
            Candidate(
                identifier=f"hist_gb_{index + 1}",
                family="hist_gradient_boosting",
                parameters=dict(spec),
            )
        )
    return candidates


def build_model(candidate: Candidate, seed: int):
    if candidate.family == "logistic_regression":
        numeric = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        return Pipeline(
            [
                (
                    "preprocessing",
                    ColumnTransformer(
                        [("numeric", numeric, list(MODEL_FEATURES))],
                        remainder="drop",
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(random_state=seed, **candidate.parameters),
                ),
            ]
        )
    if candidate.family == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=seed, **candidate.parameters)
    raise ValueError(f"unknown candidate family: {candidate.family}")


def fit_model(model, candidate: Candidate, frame, labels, weights):
    values = (
        frame.loc[:, list(MODEL_FEATURES)]
        if candidate.family == "logistic_regression"
        else frame.loc[:, list(MODEL_FEATURES)].to_numpy(dtype=float)
    )
    model.fit(values, labels, **_weight_kwargs(candidate, weights))
    return model


def _weight_kwargs(candidate: Candidate, weights) -> dict:
    if candidate.family == "logistic_regression":
        return {"classifier__sample_weight": weights}
    return {"sample_weight": weights}


def predict(model, candidate: Candidate, frame) -> np.ndarray:
    values = (
        frame.loc[:, list(MODEL_FEATURES)]
        if candidate.family == "logistic_regression"
        else frame.loc[:, list(MODEL_FEATURES)].to_numpy(dtype=float)
    )
    return np.asarray(model.predict_proba(values)[:, 1], dtype=float)
