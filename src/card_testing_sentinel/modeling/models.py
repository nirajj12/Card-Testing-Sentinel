"""Small explicit builders for the two approved model families."""

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def build_logistic_regression(C: float, seed: int) -> Pipeline:
    return Pipeline(
        [
            ("standard_scaler", StandardScaler()),
            (
                "logistic_regression",
                LogisticRegression(C=C, max_iter=2000, random_state=seed),
            ),
        ]
    )


def build_hist_gradient_boosting(
    config: dict, seed: int
) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=float(config["learning_rate"]),
        max_leaf_nodes=int(config["max_leaf_nodes"]),
        max_iter=int(config["max_iter"]),
        min_samples_leaf=int(config["min_samples_leaf"]),
        l2_regularization=float(config["l2_regularization"]),
        random_state=seed,
    )
