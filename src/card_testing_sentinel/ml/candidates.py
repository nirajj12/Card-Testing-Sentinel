from collections.abc import Iterable

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from card_testing_sentinel.features.specification import MODEL_FEATURES


def candidate_specs(config: dict) -> Iterable[dict]:
    logistic = config["candidate_grids"]["logistic_regression"]
    for value in logistic["C"]:
        yield {
            "family": "logistic_regression",
            "parameters": {"C": float(value), "max_iter": logistic["max_iter"]},
        }
    for parameters in config["candidate_grids"]["hist_gradient_boosting"]:
        yield {
            "family": "hist_gradient_boosting",
            "parameters": dict(parameters),
        }


def build_candidate(family: str, parameters: dict, seed: int):
    if family == "logistic_regression":
        numeric = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        preprocessing = ColumnTransformer(
            [("numeric", numeric, list(MODEL_FEATURES))],
            remainder="drop",
            verbose_feature_names_out=False,
        )
        return Pipeline(
            [
                ("preprocessing", preprocessing),
                (
                    "classifier",
                    LogisticRegression(
                        C=parameters["C"],
                        max_iter=parameters["max_iter"],
                        random_state=seed,
                    ),
                ),
            ]
        )
    if family == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            **parameters, random_state=seed, early_stopping=False
        )
    raise ValueError(f"unknown candidate family: {family}")


def fit_candidate(model, family: str, x, y, sample_weight):
    if tuple(x.columns) != MODEL_FEATURES:
        raise ValueError(
            "models must receive the centralized feature allowlist directly"
        )
    if family == "logistic_regression":
        model.fit(x, y, classifier__sample_weight=sample_weight)
    else:
        model.fit(x, y, sample_weight=sample_weight)
    return model
