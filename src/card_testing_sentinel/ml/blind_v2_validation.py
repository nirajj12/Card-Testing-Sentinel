"""Dataset-only validation and shift diagnostics for unevaluated Blind v2."""

from __future__ import annotations

import ast
import pathlib

import numpy as np
import pandas as pd

from card_testing_sentinel.features.specification_v2 import MODEL_FEATURES_V2
from card_testing_sentinel.ml.validation import (
    OUTCOME_ONLY_FIELDS,
    DatasetValidator,
    ValidationReport,
    _overlap_coefficient,
)
from card_testing_sentinel.ml.validation_features_v2 import (
    check_contract,
    check_customer_missingness,
    check_overlap,
    check_shuffled_labels,
    check_univariate_leakage,
)

IDENTITY_COLUMNS = (
    "event_id",
    "request_id",
    "device_id",
    "customer_id",
    "session_id",
    "ip_fingerprint",
    "merchant_id",
)
FORBIDDEN_DEPENDENCIES = (
    "card_testing_sentinel.modeling",
    "card_testing_sentinel.policy",
    "card_testing_sentinel.ml.training",
    "card_testing_sentinel.ml.training_v2",
    "card_testing_sentinel.ml.evaluation",
    "card_testing_sentinel.ml.evaluation_v2",
    "card_testing_sentinel.ml.policy_search",
    "card_testing_sentinel.ml.policy_search_v2",
)


def _module_path(root: pathlib.Path, module: str) -> pathlib.Path | None:
    path = root / "src" / pathlib.Path(*module.split(".")).with_suffix(".py")
    return path if path.is_file() else None


def transitive_imports(root: pathlib.Path, entries: tuple[str, ...]) -> set[str]:
    seen: set[str] = set()
    queue = list(entries)
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(root, module)
        if path is None:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            queue.extend(
                name for name in names if name.startswith("card_testing_sentinel")
            )
    return seen


def check_generator_independence(
    root: pathlib.Path, entries: tuple[str, ...], report: ValidationReport
) -> None:
    reachable = transitive_imports(root, entries)
    violations = sorted(
        module
        for module in reachable
        if any(
            module == forbidden or module.startswith(forbidden + ".")
            for forbidden in FORBIDDEN_DEPENDENCIES
        )
    )
    report.require(not violations, f"Blind v2 generator reaches {violations}")
    report.summary["generator_reachable_modules"] = sorted(reachable)


def check_no_label_conditioned_actor_branches(
    generator_path: pathlib.Path, report: ValidationReport
) -> None:
    tree = ast.parse(generator_path.read_text())
    actor = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == "_generate_actor"
    )
    violations = []
    for node in ast.walk(actor):
        if not isinstance(node, ast.If | ast.IfExp | ast.While):
            continue
        test = ast.unparse(node.test).lower()
        if "population" in test or "label" in test:
            violations.append(test)
    report.require(
        not violations,
        f"actor event generation branches on label/population: {violations}",
    )


def check_identity_independence(
    blind_raw: pd.DataFrame,
    references: dict[str, pd.DataFrame],
    report: ValidationReport,
) -> None:
    result: dict[str, dict[str, int]] = {}
    for reference_name, reference in references.items():
        overlaps = {}
        for column in IDENTITY_COLUMNS:
            if column not in reference or column not in blind_raw:
                continue
            shared = set(blind_raw[column].dropna()) & set(reference[column].dropna())
            overlaps[column] = len(shared)
            report.require(
                not shared,
                f"Blind v2 reuses {len(shared)} {reference_name} {column} values",
            )
        result[reference_name] = overlaps
    report.summary["identity_overlap"] = result


def check_temporal_isolation(
    blind_raw: pd.DataFrame,
    development_raw: pd.DataFrame,
    report: ValidationReport,
) -> None:
    blind = pd.to_datetime(blind_raw.timestamp, format="ISO8601")
    development = pd.to_datetime(development_raw.timestamp, format="ISO8601")
    report.require(blind.min() > development.max(), "Blind v2 overlaps Dataset v3")
    report.summary["temporal"] = {
        "dataset_v3_last_event": str(development.max()),
        "blind_v2_first_event": str(blind.min()),
        "blind_v2_last_event": str(blind.max()),
        "separation_days": round(
            float((blind.min() - development.max()).total_seconds() / 86400), 3
        ),
    }


def check_realization(
    config: dict, raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
) -> None:
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    configured_scenarios = set(config["scenarios"])
    configured_kinds = set(config["merchants"]["kinds"])
    report.require(
        set(labels.scenario) == configured_scenarios,
        "scenario realization mismatch: "
        f"{sorted(configured_scenarios - set(labels.scenario))}",
    )
    report.require(
        set(labels.merchant_kind) == configured_kinds,
        "merchant realization mismatch: "
        f"{sorted(configured_kinds - set(labels.merchant_kind))}",
    )
    active = set(requests.device_id)
    labelled_attack = set(labels.loc[labels.label.eq(1), "device_id"])
    report.require(
        labelled_attack <= active,
        f"{len(labelled_attack - active)} labelled attack devices never transact",
    )
    for name, spec in config["scenarios"].items():
        declared = set(spec.get("merchant_kinds", ()))
        if declared:
            used = set(labels.loc[labels.scenario.eq(name), "merchant_kind"])
            report.require(
                used <= declared, f"{name} used undeclared merchants {used-declared}"
            )

    scenario_devices = labels.groupby("scenario").device_id.nunique()
    request_labels = requests.merge(
        labels[["device_id", "scenario", "population"]].drop_duplicates("device_id"),
        on="device_id",
        how="left",
    )
    scenario_requests = request_labels.groupby("scenario").size()
    min_devices = int(config["gates"]["min_scenario_devices"])
    thin_devices = scenario_devices.loc[scenario_devices < min_devices].to_dict()
    report.require(not thin_devices, f"thin scenario devices: {thin_devices}")
    min_requests = int(config["gates"]["min_scenario_requests"])
    thin_requests = scenario_requests.loc[scenario_requests < min_requests].to_dict()
    report.require(not thin_requests, f"thin scenario requests: {thin_requests}")
    shares = request_labels.groupby(["population", "scenario"]).size()
    shares = shares / shares.groupby(level=0).transform("sum")
    max_share = float(config["gates"]["max_scenario_request_share"])
    dominant = shares.loc[shares > max_share].to_dict()
    report.require(not dominant, f"scenario request dominance: {dominant}")
    report.summary["realization"] = {
        "scenario_devices": {str(k): int(v) for k, v in scenario_devices.items()},
        "scenario_requests": {str(k): int(v) for k, v in scenario_requests.items()},
        "merchant_kinds": sorted(set(labels.merchant_kind)),
        "active_attack_devices": len(labelled_attack & active),
        "labelled_attack_devices": len(labelled_attack),
    }


def check_causality(raw: pd.DataFrame, report: ValidationReport) -> None:
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    for column in OUTCOME_ONLY_FIELDS:
        report.require(
            requests[column].isna().all(),
            f"request carries future/current outcome field {column}",
        )
    forbidden = {"label", "population", "scenario", "actor_id", "linkage_class"}
    report.require(
        not (forbidden & set(raw.columns)),
        f"raw events expose evaluation metadata {forbidden & set(raw.columns)}",
    )


def check_identity_segments(
    raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
) -> None:
    requests = raw.loc[raw.event_type.eq("authorization_request")].merge(
        labels[["device_id", "label"]].drop_duplicates("device_id"),
        on="device_id",
        how="left",
    )
    requests["identity"] = np.where(requests.customer_id.notna(), "logged_in", "guest")
    requests["population"] = np.where(requests.label.eq(1), "attack", "legitimate")
    cells = requests.groupby(["population", "identity"]).size().to_dict()
    for population in ("attack", "legitimate"):
        for identity in ("guest", "logged_in"):
            report.require(
                cells.get((population, identity), 0) > 0,
                f"missing {identity} {population} requests",
            )
    report.summary["identity_segments"] = {
        f"{population}_{identity}": int(count)
        for (population, identity), count in cells.items()
    }


def check_behavioral_requirements(
    raw: pd.DataFrame,
    labels: pd.DataFrame,
    features: pd.DataFrame,
    report: ValidationReport,
) -> None:
    requests = raw.loc[raw.event_type.eq("authorization_request")].merge(
        labels[
            ["device_id", "actor_id", "scenario", "label", "linkage_class"]
        ].drop_duplicates("device_id"),
        on="device_id",
        how="left",
    )
    requests["day"] = pd.to_datetime(requests.timestamp, format="ISO8601").dt.date
    actor_devices = labels.groupby(["actor_id", "label"]).device_id.nunique()
    legitimate_multi = actor_devices.loc[
        (actor_devices.index.get_level_values("label") == 0) & actor_devices.ge(2)
    ]
    attack_multi = actor_devices.loc[
        (actor_devices.index.get_level_values("label") == 1) & actor_devices.ge(2)
    ]
    report.require(len(legitimate_multi) > 0, "no legitimate multi-device actors")
    report.require(len(attack_multi) > 0, "no cross-device attack actors")

    patient_names = {"patient_tester_v2", "ultra_patient_v2"}
    patient = features.loc[features.scenario.isin(patient_names)]
    low_velocity = float(patient.requests_24h.le(2).mean()) if len(patient) else 0.0
    report.require(
        low_velocity >= 0.60, f"patient requests_24h<=2 share only {low_velocity:.3f}"
    )
    patient_raw = requests.loc[requests.scenario.isin(patient_names)]
    patient_actor_attempts = patient_raw.groupby("actor_id").size()
    report.require(
        bool(patient_actor_attempts.between(3, 8).all()),
        "patient actors fall outside 3-8 main/warm-up attempts",
    )

    sparse = requests.loc[requests.scenario.eq("sparse_multiday_v2")]
    sparse_days = sparse.groupby("actor_id").day.nunique()
    report.require(bool((sparse_days >= 2).all()), "sparse actors are not multiday")

    dunning = features.loc[features.scenario.eq("subscription_dunning_v2")]
    report.require(len(dunning) > 0, "subscription dunning absent")
    report.require(
        bool(
            dunning.failures_7d.gt(0).any()
            and dunning.successful_checkouts_30d.gt(0).any()
        ),
        "dunning lacks overlapping failures and successful history",
    )

    warmup = features.loc[features.scenario.eq("warm_up_then_attack_v2")]
    report.require(
        bool(warmup.successful_checkouts_30d.gt(0).any()),
        "warm-up attacks never carry successful 30-day history",
    )

    ip_devices = requests.groupby("ip_fingerprint").device_id.nunique()
    shared_ips = set(ip_devices.loc[ip_devices.ge(2)].index)
    shared = requests.loc[requests.ip_fingerprint.isin(shared_ips)]
    populations = set(shared.label.dropna().astype(int))
    report.require(
        populations == {0, 1}, "shared IP infrastructure lacks population overlap"
    )
    report.summary["behavioral_requirements"] = {
        "legitimate_multi_device_actors": int(len(legitimate_multi)),
        "cross_device_attack_actors": int(len(attack_multi)),
        "patient_low_velocity_request_share": round(low_velocity, 4),
        "patient_actor_attempts": {
            "min": int(patient_actor_attempts.min()),
            "median": float(patient_actor_attempts.median()),
            "max": int(patient_actor_attempts.max()),
        },
        "sparse_active_days": {
            "min": int(sparse_days.min()),
            "median": float(sparse_days.median()),
            "max": int(sparse_days.max()),
        },
        "shared_ips": int(len(shared_ips)),
        "shared_ip_legitimate_requests": int(shared.label.eq(0).sum()),
        "shared_ip_attack_requests": int(shared.label.eq(1).sum()),
    }


def check_decline_realism(
    config: dict, raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
) -> None:
    outcomes = raw.loc[raw.event_type.eq("authorization_outcome")].merge(
        labels[["device_id", "label"]].drop_duplicates("device_id"),
        on="device_id",
        how="left",
    )
    legitimate = float(
        outcomes.loc[outcomes.label.eq(0), "authorization_result"].eq("declined").mean()
    )
    band = config["gates"]["legitimate_decline_rate"]
    report.require(
        float(band["fail_below"]) <= legitimate <= float(band["fail_above"]),
        f"legitimate decline rate {legitimate:.3f} outside {band}",
    )
    if not float(band["warn_below"]) <= legitimate <= float(band["warn_above"]):
        report.warnings.append(
            "legitimate decline rate "
            f"{legitimate:.3f} outside warning band "
            f"[{float(band['warn_below']):.3f}, {float(band['warn_above']):.3f}]"
        )
    report.summary["decline_rate"] = {
        "legitimate": round(legitimate, 4),
        "overall": round(float(outcomes.authorization_result.eq("declined").mean()), 4),
    }


def population_stability_index(reference: np.ndarray, candidate: np.ndarray) -> float:
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, 11)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    left = np.histogram(reference, bins=edges)[0] / max(len(reference), 1)
    right = np.histogram(candidate, bins=edges)[0] / max(len(candidate), 1)
    left = np.clip(left, 1e-6, None)
    right = np.clip(right, 1e-6, None)
    return float(np.sum((right - left) * np.log(right / left)))


def kolmogorov_smirnov(reference: np.ndarray, candidate: np.ndarray) -> float:
    combined = np.sort(np.concatenate([reference, candidate]))
    left = np.searchsorted(np.sort(reference), combined, side="right") / len(reference)
    right = np.searchsorted(np.sort(candidate), combined, side="right") / len(candidate)
    return float(np.max(np.abs(left - right)))


def feature_shift_report(
    development: pd.DataFrame, blind: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    for name in MODEL_FEATURES_V2:
        reference = development[name].to_numpy(dtype=float)
        candidate = blind[name].to_numpy(dtype=float)
        rows.append(
            {
                "feature": name,
                "development_median": round(float(np.median(reference)), 4),
                "blind_v2_median": round(float(np.median(candidate)), 4),
                "development_p90": round(float(np.quantile(reference, 0.9)), 4),
                "blind_v2_p90": round(float(np.quantile(candidate, 0.9)), 4),
                "psi": round(population_stability_index(reference, candidate), 4),
                "ks": round(kolmogorov_smirnov(reference, candidate), 4),
                "overlap_coefficient": round(
                    _overlap_coefficient(reference, candidate), 4
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("psi", ascending=False).reset_index(drop=True)


def validate_blind_v2(
    *,
    root: pathlib.Path,
    config: dict,
    raw: pd.DataFrame,
    labels: pd.DataFrame,
    features: pd.DataFrame,
    development_raw: pd.DataFrame,
    blind_v1_raw: pd.DataFrame,
    generator_entries: tuple[str, ...],
) -> ValidationReport:
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_lifecycle(raw, report)
    check_contract(features, report)
    check_univariate_leakage(
        features, report, cap=float(config["gates"]["max_univariate_f1"])
    )
    check_shuffled_labels(
        features, report, cap=float(config["gates"]["max_shuffled_label_roc_auc"])
    )
    check_overlap(
        features, report, floor=float(config["gates"]["min_overlap_coefficient"])
    )
    check_customer_missingness(features, report, cap=0.70)
    check_generator_independence(root, generator_entries, report)
    check_no_label_conditioned_actor_branches(
        root / "src/card_testing_sentinel/ml/blind_v2_generator.py", report
    )
    check_identity_independence(
        raw, {"dataset_v3": development_raw, "blind_v1_1": blind_v1_raw}, report
    )
    check_temporal_isolation(raw, development_raw, report)
    check_realization(config, raw, labels, report)
    check_causality(raw, report)
    check_identity_segments(raw, labels, report)
    check_behavioral_requirements(raw, labels, features, report)
    check_decline_realism(config, raw, labels, report)
    report.summary["contains_model_scores"] = False
    report.summary["contains_policy_decisions"] = False
    report.summary["evaluated"] = False
    report.summary["consumed"] = False
    return report
