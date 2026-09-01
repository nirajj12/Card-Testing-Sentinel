"""Dataset validation and leakage gates.

Catches broken or artificially easy synthetic data *before* anyone trains on
it. Three groups of checks:

* lifecycle / split / feature integrity -- hard failures, the data is wrong
* leakage gates -- a single feature that nearly solves the task, or a
  pipeline that "learns" from shuffled labels, means the generator is wrong
* distribution + overlap reporting -- readable EDA so a human can see whether
  the two populations actually overlap

When a gate fails the correct response is to change the generator and
regenerate. Nothing here deletes or rewrites a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from card_testing_sentinel.features.specification import (
    FORBIDDEN_TERMS,
    MODEL_FEATURES,
)

#: Features whose distributions must visibly overlap between populations.
OVERLAP_FEATURES = (
    "current_amount",
    "requests_5m",
    "failure_ratio_24h",
    "sessions_24h",
    "ip_changes_24h",
    "low_amount_ratio_24h",
)

#: Request events may never carry any of these -- they are outcome-only.
OUTCOME_ONLY_FIELDS = (
    "authorization_result",
    "failure_reason",
    "payment_method",
    "card_last4",
    "card_network",
    "card_type",
    "card_issuer",
    "international",
)


@dataclass
class ValidationReport:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.failures.append(message)

    def as_dict(self) -> dict:
        return {
            "status": "passed" if self.passed else "failed",
            "failures": self.failures,
            "warnings": self.warnings,
            "summary": self.summary,
        }


class DatasetValidator:
    def __init__(self, gates: dict):
        self.max_univariate_f1 = float(gates["max_univariate_f1"])
        self.max_shuffled_auc = float(gates["max_shuffled_label_roc_auc"])
        self.min_overlap = float(gates["min_overlap_coefficient"])
        self.min_scenario_devices = int(gates["min_scenario_devices"])
        self.min_scenario_requests = int(gates["min_scenario_requests"])
        self.decline_band = dict(gates["legitimate_decline_rate"])
        self.max_scenario_request_share = float(gates["max_scenario_request_share"])
        #: The everyday-shopper scenarios, reported separately so the
        #: realistic merchant-book decline rate stays visible next to the
        #: deliberately inflated aggregate.
        self.ordinary_scenarios = tuple(gates["ordinary_legitimate_scenarios"])

    # -- integrity ---------------------------------------------------------

    def check_lifecycle(self, raw: pd.DataFrame, report: ValidationReport) -> None:
        requests = raw.loc[raw.event_type.eq("authorization_request")]
        outcomes = raw.loc[raw.event_type.eq("authorization_outcome")]
        checkouts = raw.loc[raw.event_type.eq("checkout_completion")]

        report.require(not raw.event_id.duplicated().any(), "duplicate event_id")
        report.require(
            not requests.request_id.duplicated().any(), "duplicate request_id"
        )
        report.require(
            not outcomes.request_id.duplicated().any(),
            "a request received more than one outcome",
        )
        report.require(
            outcomes.request_id.isin(set(requests.request_id)).all(),
            "outcome without a matching request",
        )
        approved = set(
            outcomes.loc[outcomes.authorization_result.eq("approved"), "request_id"]
        )
        report.require(
            checkouts.request_id.isin(approved).all(),
            "checkout completion without an approved payment",
        )

        for column in OUTCOME_ONLY_FIELDS:
            report.require(
                requests[column].isna().all(),
                f"request events carry outcome-only field '{column}'",
            )
        report.require(
            requests.merchant_id.notna().all(), "request without a merchant_id"
        )
        report.require(
            requests.amount.notna().all() and (requests.amount > 0).all(),
            "request with a missing or non-positive amount",
        )

        times = raw.assign(ts=pd.to_datetime(raw.timestamp, format="ISO8601"))
        request_time = times.loc[
            times.event_type.eq("authorization_request"), ["request_id", "ts"]
        ].set_index("request_id")["ts"]
        outcome_time = times.loc[
            times.event_type.eq("authorization_outcome"), ["request_id", "ts"]
        ].set_index("request_id")["ts"]
        aligned = outcome_time.index.intersection(request_time.index)
        report.require(
            bool((outcome_time[aligned] > request_time[aligned]).all()),
            "an outcome is not strictly after its request",
        )
        # Per device, (timestamp, event_sequence) must never go backwards or
        # the live engine would reject the replay.
        ordered = times.sort_values(["timestamp", "event_sequence"], kind="mergesort")
        backwards = ordered.groupby("device_id").event_sequence.apply(
            lambda values: bool((values.diff().dropna() < 0).any())
        )
        report.require(
            not bool(backwards.any()), "per-device event order goes backwards"
        )

    def check_splits(
        self, labels: pd.DataFrame, raw: pd.DataFrame, report: ValidationReport
    ) -> None:
        by_split = labels.groupby("split").device_id.apply(set)
        report.require(
            set(by_split.index) == {"train", "validation"},
            "expected exactly a train and a validation split",
        )
        if len(by_split) == 2:
            train, validation = by_split["train"], by_split["validation"]
            report.require(not (train & validation), "device overlap across splits")

        times = raw.assign(ts=pd.to_datetime(raw.timestamp, format="ISO8601"))
        windows = times.groupby("split").ts.agg(["min", "max"])
        if {"train", "validation"} <= set(windows.index):
            train_last = windows.loc["train", "max"]
            validation_first = windows.loc["validation", "min"]
            # Strict temporal separation: the LAST training event must precede
            # the FIRST validation event, so no long-horizon training actor
            # bleeds across the boundary.
            report.require(
                train_last < validation_first,
                "temporal separation violated: the last training event "
                f"({train_last}) is not before the first validation event "
                f"({validation_first})",
            )
            report.summary["windows"] = {
                split: {"min": str(row["min"]), "max": str(row["max"])}
                for split, row in windows.iterrows()
            }
            report.summary["temporal_separation_seconds"] = round(
                float((validation_first - train_last).total_seconds()), 1
            )
        for column in ("event_id", "request_id"):
            overlap = set(raw.loc[raw.split.eq("train"), column].dropna()) & set(
                raw.loc[raw.split.eq("validation"), column].dropna()
            )
            report.require(not overlap, f"{column} reused across splits")

    def check_features(self, features: pd.DataFrame, report: ValidationReport) -> None:
        ordered = [name for name in features.columns if name in set(MODEL_FEATURES)]
        report.require(
            tuple(ordered) == MODEL_FEATURES,
            "feature table columns do not match the contract order",
        )
        values = features.loc[:, list(MODEL_FEATURES)].to_numpy(dtype=float)
        report.require(bool(np.isfinite(values).all()), "non-finite feature value")
        report.require(
            not features.loc[:, list(MODEL_FEATURES)].isna().any().any(),
            "missing feature value",
        )
        unsafe = [
            name
            for name in MODEL_FEATURES
            if any(term in name for term in FORBIDDEN_TERMS)
        ]
        report.require(not unsafe, f"forbidden feature names: {unsafe}")
        report.require(
            features.label.isin({0, 1}).all(), "feature rows carry a non-binary label"
        )

    # -- leakage gates -----------------------------------------------------

    def check_univariate_leakage(
        self, features: pd.DataFrame, report: ValidationReport
    ) -> None:
        """No single feature may nearly solve the task on its own.

        A useful feature is *supposed* to be predictive -- this only catches a
        feature that is effectively the label wearing a different name.
        """
        labels = features.label.to_numpy(dtype=int)
        rows = []
        for name in MODEL_FEATURES:
            values = features[name].to_numpy(dtype=float)
            best = 0.0
            for signed in (values, -values):
                precision, recall, _ = precision_recall_curve(labels, signed)
                f1 = (
                    2
                    * precision[:-1]
                    * recall[:-1]
                    / np.maximum(precision[:-1] + recall[:-1], 1e-12)
                )
                best = max(best, float(f1.max()) if f1.size else 0.0)
            rows.append({"feature": name, "max_f1": round(best, 4)})
            report.require(
                best <= self.max_univariate_f1,
                f"feature '{name}' alone reaches F1 {best:.3f} "
                f"(> {self.max_univariate_f1}); investigate the generator",
            )
        table = pd.DataFrame(rows).sort_values("max_f1", ascending=False)
        report.summary["univariate_max_f1"] = table.head(8).to_dict("records")

    def check_shuffled_labels(
        self, features: pd.DataFrame, report: ValidationReport, seed: int = 7
    ) -> None:
        """A diagnostic classifier trained on shuffled labels must be close to
        random. This is a pipeline sanity check, not a model result."""
        rng = np.random.default_rng(seed)
        values = features.loc[:, list(MODEL_FEATURES)].to_numpy(dtype=float)
        shuffled = rng.permutation(features.label.to_numpy(dtype=int))
        x_train, x_test, y_train, y_test = train_test_split(
            values, shuffled, test_size=0.3, random_state=seed, stratify=shuffled
        )
        scaler = StandardScaler().fit(x_train)
        probe = LogisticRegression(max_iter=200).fit(scaler.transform(x_train), y_train)
        auc = float(
            roc_auc_score(y_test, probe.predict_proba(scaler.transform(x_test))[:, 1])
        )
        report.summary["shuffled_label_roc_auc"] = round(auc, 4)
        report.require(
            auc <= self.max_shuffled_auc,
            f"shuffled-label ROC-AUC {auc:.3f} > {self.max_shuffled_auc}: "
            "the pipeline is leaking label information",
        )

    def check_overlap(self, features: pd.DataFrame, report: ValidationReport) -> None:
        """Populations must genuinely overlap. Near-disjoint distributions
        mean the task is fake, even when no single F1 gate fires."""
        legitimate = features.loc[features.label.eq(0)]
        attack = features.loc[features.label.eq(1)]
        overlaps = {}
        for name in OVERLAP_FEATURES:
            coefficient = _overlap_coefficient(
                legitimate[name].to_numpy(dtype=float),
                attack[name].to_numpy(dtype=float),
            )
            overlaps[name] = round(coefficient, 4)
            report.require(
                coefficient >= self.min_overlap,
                f"'{name}' distributions barely overlap "
                f"({coefficient:.2f} < {self.min_overlap}); widen the scenario ranges",
            )
        report.summary["overlap_coefficient"] = overlaps

    # -- realism gates -----------------------------------------------------

    def check_outcome_realism(
        self, raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
    ) -> None:
        """The legitimate population's aggregate decline rate must be
        plausible for a merchant's book.

        Individual scenarios may fail constantly -- that is the point of the
        hard tail. What must stay believable is the *mixture*: ordinary
        customers have to dominate the aggregate. The band is configuration,
        not an industry claim, and it warns before it fails.
        """
        device_label = labels[["device_id", "label"]].drop_duplicates("device_id")
        outcomes = raw.loc[raw.event_type.eq("authorization_outcome")].merge(
            device_label, on="device_id", how="left"
        )
        rates = (
            outcomes.groupby("label")
            .authorization_result.apply(
                lambda values: float(values.eq("declined").mean())
            )
            .to_dict()
        )
        legitimate = float(rates.get(0, 0.0))

        # The aggregate sits above an ordinary merchant's book because this
        # benchmark deliberately over-represents retry-heavy legitimate
        # behaviour. Reporting the ordinary-customer subset alongside it keeps
        # that visible instead of hiding it inside one number.
        scenarios = labels[["device_id", "scenario"]].drop_duplicates("device_id")
        ordinary = outcomes.merge(scenarios, on="device_id", how="left")
        ordinary = ordinary.loc[ordinary.scenario.isin(self.ordinary_scenarios)]
        report.summary["decline_rate"] = {
            "legitimate": round(legitimate, 4),
            "legitimate_ordinary_customers": (
                round(float(ordinary.authorization_result.eq("declined").mean()), 4)
                if len(ordinary)
                else None
            ),
            "attack": round(float(rates.get(1, 0.0)), 4),
            "overall": round(
                float(outcomes.authorization_result.eq("declined").mean()), 4
            ),
            "band": self.decline_band,
            "note": (
                "The legitimate aggregate is inflated on purpose: retry-heavy "
                "scenarios exist to stress false positives and make more "
                "attempts each. `legitimate_ordinary_customers` is the "
                "realistic merchant-book figure."
            ),
        }
        band = self.decline_band
        report.require(
            float(band["fail_below"]) <= legitimate <= float(band["fail_above"]),
            f"legitimate decline rate {legitimate:.3f} is outside the plausible "
            f"band [{band['fail_below']}, {band['fail_above']}]; rebalance the "
            "legitimate scenario mixture rather than raising approval globally",
        )
        if not float(band["warn_below"]) <= legitimate <= float(band["warn_above"]):
            report.warnings.append(
                f"legitimate decline rate {legitimate:.3f} sits outside the "
                f"comfortable band [{band['warn_below']}, {band['warn_above']}]"
            )

    def check_scenario_balance(
        self, raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
    ) -> None:
        """Every scenario must be represented, and none may quietly become
        the benchmark by out-attempting the rest of its population."""
        from card_testing_sentinel.ml.generator import scenario_profile

        profile = scenario_profile(raw, labels)
        report.summary["scenario_profile"] = profile.to_dict("index")

        thin_devices = profile.loc[
            profile.devices < self.min_scenario_devices, "devices"
        ].to_dict()
        report.require(
            not thin_devices, f"scenarios with too few devices: {thin_devices}"
        )
        thin_requests = profile.loc[
            profile.requests < self.min_scenario_requests, "requests"
        ].to_dict()
        report.require(
            not thin_requests, f"scenarios with too few requests: {thin_requests}"
        )
        dominant = profile.loc[
            profile.share_of_population_requests > self.max_scenario_request_share,
            "share_of_population_requests",
        ].to_dict()
        report.require(
            not dominant,
            f"scenarios dominating their population's requests "
            f"(> {self.max_scenario_request_share}): {dominant}",
        )

    # -- EDA ---------------------------------------------------------------

    def describe(
        self, raw: pd.DataFrame, labels: pd.DataFrame, features: pd.DataFrame
    ) -> dict:
        requests = raw.loc[raw.event_type.eq("authorization_request")]
        outcomes = raw.loc[raw.event_type.eq("authorization_outcome")]
        by_device = requests.groupby("device_id").size()
        declines = outcomes.loc[outcomes.authorization_result.eq("declined")]

        def population_stats(column: str) -> dict:
            grouped = features.groupby("label")[column]
            return {
                ("legitimate" if key == 0 else "attack"): {
                    "mean": round(float(group.mean()), 3),
                    "median": round(float(group.median()), 3),
                    "p90": round(float(group.quantile(0.90)), 3),
                }
                for key, group in grouped
            }

        return {
            "devices": int(labels.device_id.nunique()),
            "merchants": int(labels.merchant_id.nunique()),
            "requests": int(len(requests)),
            "outcomes": int(len(outcomes)),
            "checkouts": int(raw.event_type.eq("checkout_completion").sum()),
            "class_balance_devices": {
                "legitimate": int(labels.loc[labels.label.eq(0)].device_id.nunique()),
                "attack": int(labels.loc[labels.label.eq(1)].device_id.nunique()),
            },
            "class_balance_requests": {
                "legitimate": int(features.label.eq(0).sum()),
                "attack": int(features.label.eq(1).sum()),
            },
            "scenario_devices": labels.groupby("scenario")
            .device_id.nunique()
            .to_dict(),
            "merchant_kind_devices": (
                labels.groupby("merchant_kind").device_id.nunique().to_dict()
            ),
            "attempts_per_device": {
                "mean": round(float(by_device.mean()), 3),
                "median": float(by_device.median()),
                "p90": float(by_device.quantile(0.90)),
                "max": int(by_device.max()),
            },
            "overall_decline_rate": round(
                float(len(declines) / max(len(outcomes), 1)), 4
            ),
            "by_population": {
                name: population_stats(name)
                for name in (
                    "current_amount",
                    "requests_5m",
                    "seconds_since_last_request",
                    "failure_ratio_24h",
                    "sessions_24h",
                    "ip_changes_24h",
                    "low_amount_ratio_24h",
                    "distinct_card_last4_7d",
                )
            },
        }

    # -- entry point -------------------------------------------------------

    def validate(
        self, raw: pd.DataFrame, labels: pd.DataFrame, features: pd.DataFrame
    ) -> ValidationReport:
        report = ValidationReport()
        self.check_lifecycle(raw, report)
        self.check_splits(labels, raw, report)
        self.check_features(features, report)
        self.check_univariate_leakage(features, report)
        self.check_shuffled_labels(features, report)
        self.check_overlap(features, report)
        self.check_outcome_realism(raw, labels, report)
        self.check_scenario_balance(raw, labels, report)
        report.summary["eda"] = self.describe(raw, labels, features)
        return report


def _overlap_coefficient(left: np.ndarray, right: np.ndarray, bins: int = 40) -> float:
    """Histogram overlap of two samples on a shared binning: 1.0 means the
    distributions are indistinguishable, 0.0 means they are disjoint."""
    if left.size == 0 or right.size == 0:
        return 0.0
    combined = np.concatenate([left, right])
    low, high = float(np.min(combined)), float(np.max(combined))
    if high <= low:
        return 1.0
    edges = np.linspace(low, high, bins + 1)
    left_density, _ = np.histogram(left, bins=edges, density=False)
    right_density, _ = np.histogram(right, bins=edges, density=False)
    left_share = left_density / max(left_density.sum(), 1)
    right_share = right_density / max(right_density.sum(), 1)
    return float(np.minimum(left_share, right_share).sum())
