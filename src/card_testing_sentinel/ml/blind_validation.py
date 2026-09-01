"""Blind-benchmark gates and the feature-only distribution-shift report.

Everything here runs *before* the frozen model is pointed at the blind set.
It inspects raw events, labels and features -- never a prediction, a score or
a policy decision -- so running it does not consume the benchmark.

The gates that matter most here are the ones development cannot have:
independence (no identity shared with train or validation) and temporal
separation (the blind window opens strictly after development ends).
"""

from __future__ import annotations

import ast
import pathlib

import numpy as np
import pandas as pd

from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.validation import (
    DatasetValidator,
    ValidationReport,
    _overlap_coefficient,
)

#: Modules the blind generation path may never depend on, directly or
#: transitively. Reading any of these would let a development result leak
#: into the design of the benchmark meant to test it.
FORBIDDEN_DEPENDENCIES = (
    "card_testing_sentinel.modeling",
    "card_testing_sentinel.policy",
    "card_testing_sentinel.ml.training",
    "card_testing_sentinel.ml.evaluation",
    "card_testing_sentinel.ml.policy_search",
    "card_testing_sentinel.ml.generator",
)

#: Identity columns that must be disjoint between development and blind.
IDENTITY_COLUMNS = (
    "device_id",
    "customer_id",
    "session_id",
    "request_id",
    "event_id",
    "ip_fingerprint",
)


def _module_path(root: pathlib.Path, module: str) -> pathlib.Path | None:
    candidate = root / "src" / pathlib.Path(*module.split(".")).with_suffix(".py")
    return candidate if candidate.is_file() else None


def transitive_imports(root: pathlib.Path, entry_modules: tuple[str, ...]) -> set[str]:
    """Walk the project-local import graph from the given entry modules.

    A static walk rather than a string search: it follows `from x import y`
    through every project module actually reachable, so an indirect dependency
    cannot hide behind one level of indirection.
    """
    seen: set[str] = set()
    queue = list(entry_modules)
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
            found: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module)
            elif isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            for name in found:
                if name.startswith("card_testing_sentinel"):
                    queue.append(name)
    return seen


def check_generator_independence(
    root: pathlib.Path, entry_modules: tuple[str, ...], report: ValidationReport
) -> set[str]:
    reachable = transitive_imports(root, entry_modules)
    violations = sorted(
        module
        for module in reachable
        for forbidden in FORBIDDEN_DEPENDENCIES
        if module == forbidden or module.startswith(forbidden + ".")
    )
    report.require(
        not violations,
        f"the blind generator reaches forbidden modules: {violations}",
    )
    report.summary["generator_reachable_modules"] = sorted(reachable)
    return reachable


def check_identity_independence(
    blind_raw: pd.DataFrame,
    blind_labels: pd.DataFrame,
    development_raw: pd.DataFrame,
    development_labels: pd.DataFrame,
    report: ValidationReport,
) -> None:
    """Zero overlap on every actor-owned identity, against BOTH dev splits."""
    overlaps: dict[str, int] = {}
    for column in IDENTITY_COLUMNS:
        if column not in blind_raw.columns or column not in development_raw.columns:
            continue
        shared = set(blind_raw[column].dropna()) & set(development_raw[column].dropna())
        overlaps[column] = len(shared)
        report.require(not shared, f"blind reuses {len(shared)} development {column}s")
    device_overlap = set(blind_labels.device_id) & set(development_labels.device_id)
    report.require(not device_overlap, "blind reuses development devices")
    report.summary["identity_overlap"] = overlaps


def check_temporal_separation(
    blind_raw: pd.DataFrame, development_raw: pd.DataFrame, report: ValidationReport
) -> None:
    blind = pd.to_datetime(blind_raw.timestamp, format="ISO8601")
    development = pd.to_datetime(development_raw.timestamp, format="ISO8601")
    report.require(
        blind.min() > development.max(),
        f"blind opens at {blind.min()} but development ends at {development.max()}",
    )
    report.summary["temporal"] = {
        "development_last_event": str(development.max()),
        "blind_first_event": str(blind.min()),
        "blind_last_event": str(blind.max()),
        "separation_days": round(
            (blind.min() - development.max()).total_seconds() / 86400, 3
        ),
    }


def check_merchant_composition(
    blind_labels: pd.DataFrame,
    development_labels: pd.DataFrame,
    report: ValidationReport,
    config: dict | None = None,
    blind_raw: pd.DataFrame | None = None,
) -> None:
    """Every declared merchant kind must actually be realized.

    v1.0 checked only "at least two unseen kinds", which passed while
    `ticketing_events` -- a declared unseen archetype -- had zero merchants and
    zero devices. A declared kind that never appears is a hole in the
    benchmark, so the gate now compares the configured kinds against what the
    data contains.
    """
    shared = set(blind_labels.merchant_id) & set(development_labels.merchant_id)
    report.require(not shared, f"blind reuses {len(shared)} development merchants")

    devices = blind_labels.drop_duplicates("device_id")
    unseen = set(devices.loc[devices.merchant_origin.eq("unseen"), "merchant_kind"])
    known = set(devices.loc[devices.merchant_origin.eq("known"), "merchant_kind"])
    realized = unseen | known

    configured: set[str] = set()
    configured_unseen: set[str] = set()
    if config is not None:
        kinds = config["merchants"]["kinds"]
        configured = set(kinds)
        configured_unseen = {
            name for name, spec in kinds.items() if spec.get("origin") == "unseen"
        }
        report.require(
            not configured - realized,
            "declared merchant kinds absent from the generated data: "
            f"{sorted(configured - realized)}",
        )
        report.require(
            not configured_unseen - unseen,
            "declared UNSEEN merchant kinds absent from the generated data: "
            f"{sorted(configured_unseen - unseen)}",
        )

    report.require(
        len(unseen) >= 2,
        "the blind set needs at least two unseen merchant kinds, "
        f"found {sorted(unseen)}",
    )
    development_kinds = set(development_labels.merchant_kind)
    leaked = unseen & development_kinds
    report.require(
        not leaked, f"kinds marked unseen but present in development: {sorted(leaked)}"
    )

    instances = (
        blind_labels.drop_duplicates("merchant_id")
        .groupby("merchant_kind")
        .size()
        .to_dict()
    )
    requests_per_kind: dict[str, int] = {}
    if blind_raw is not None:
        requests = blind_raw.loc[blind_raw.event_type.eq("authorization_request")]
        requests_per_kind = {
            str(kind): int(value)
            for kind, value in requests.merge(
                devices[["device_id", "merchant_kind"]], on="device_id", how="left"
            )
            .groupby("merchant_kind")
            .size()
            .items()
        }

    report.summary["merchants"] = {
        "blind_merchants": int(blind_labels.merchant_id.nunique()),
        "configured_kinds": sorted(configured),
        "realized_kinds": sorted(realized),
        "missing_kinds": sorted(configured - realized),
        "unseen_kinds": sorted(unseen),
        "known_kinds": sorted(known),
        "instances_per_kind": {str(k): int(v) for k, v in instances.items()},
        "devices_per_kind": {
            str(k): int(v)
            for k, v in devices.groupby("merchant_kind").device_id.nunique().items()
        },
        "requests_per_kind": requests_per_kind,
        "devices_on_unseen_kinds": int(
            devices.loc[devices.merchant_origin.eq("unseen")].device_id.nunique()
        ),
    }


def check_scenario_merchant_mapping(
    config: dict, blind_labels: pd.DataFrame, report: ValidationReport
) -> None:
    """A scenario that declares merchant kinds must only appear on those kinds.

    This is the data-side counterpart to removing the generator's silent
    fallback: it catches a mis-mapped family even if the fallback returns.
    """
    devices = blind_labels.drop_duplicates("device_id")
    mapping: dict[str, dict] = {}
    for name, spec in sorted(config["scenarios"].items()):
        declared = spec.get("merchant_kinds")
        if not declared:
            continue
        used = sorted(set(devices.loc[devices.scenario.eq(name), "merchant_kind"]))
        unexpected = sorted(set(used) - set(declared))
        report.require(
            not unexpected,
            f"scenario '{name}' declares merchant kinds {sorted(declared)} but "
            f"appears on {unexpected}",
        )
        mapping[name] = {"declared": sorted(declared), "used": used}
    report.summary["scenario_merchant_mapping"] = mapping


def validate_blind(
    root: pathlib.Path,
    config: dict,
    blind_raw: pd.DataFrame,
    blind_labels: pd.DataFrame,
    blind_features: pd.DataFrame,
    development_raw: pd.DataFrame,
    development_labels: pd.DataFrame,
    entry_modules: tuple[str, ...],
) -> ValidationReport:
    """Every gate the blind benchmark must clear before evaluation."""
    validator = DatasetValidator(config["gates"])
    report = ValidationReport()

    validator.check_lifecycle(blind_raw, report)
    validator.check_features(blind_features, report)
    validator.check_univariate_leakage(blind_features, report)
    validator.check_shuffled_labels(blind_features, report)
    validator.check_overlap(blind_features, report)
    validator.check_outcome_realism(blind_raw, blind_labels, report)
    validator.check_scenario_balance(blind_raw, blind_labels, report)

    check_generator_independence(root, entry_modules, report)
    check_identity_independence(
        blind_raw, blind_labels, development_raw, development_labels, report
    )
    check_temporal_separation(blind_raw, development_raw, report)
    check_merchant_composition(
        blind_labels, development_labels, report, config, blind_raw
    )
    check_scenario_merchant_mapping(config, blind_labels, report)

    report.summary["eda"] = validator.describe(blind_raw, blind_labels, blind_features)
    report.summary["contains_model_metrics"] = False
    return report


# --------------------------------------------------------------------------
# distribution shift, features only
# --------------------------------------------------------------------------


def population_stability_index(
    reference: np.ndarray, candidate: np.ndarray, bins: int = 10
) -> float:
    """PSI over quantile bins of the reference distribution.

    Conventionally: < 0.1 no meaningful shift, 0.1-0.25 moderate, > 0.25 large.
    """
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    reference_share = np.histogram(reference, bins=edges)[0] / max(len(reference), 1)
    candidate_share = np.histogram(candidate, bins=edges)[0] / max(len(candidate), 1)
    floor = 1e-6
    reference_share = np.clip(reference_share, floor, None)
    candidate_share = np.clip(candidate_share, floor, None)
    return float(
        np.sum(
            (candidate_share - reference_share)
            * np.log(candidate_share / reference_share)
        )
    )


def kolmogorov_smirnov(reference: np.ndarray, candidate: np.ndarray) -> float:
    combined = np.sort(np.concatenate([reference, candidate]))
    reference_cdf = np.searchsorted(np.sort(reference), combined, side="right") / max(
        len(reference), 1
    )
    candidate_cdf = np.searchsorted(np.sort(candidate), combined, side="right") / max(
        len(candidate), 1
    )
    return float(np.max(np.abs(reference_cdf - candidate_cdf)))


def shift_report(
    development_validation: pd.DataFrame, blind_features: pd.DataFrame
) -> pd.DataFrame:
    """Feature-only comparison of development validation against blind.

    Uses no model and no prediction, so producing it does not consume the
    benchmark. Its purpose is to confirm the blind set is genuinely shifted --
    NOT to decide whether it is acceptably hard. A hard distribution is not a
    reason to regenerate.
    """
    rows = []
    for name in MODEL_FEATURES:
        reference = development_validation[name].to_numpy(dtype=float)
        candidate = blind_features[name].to_numpy(dtype=float)
        rows.append(
            {
                "feature": name,
                "development_median": round(float(np.median(reference)), 4),
                "blind_median": round(float(np.median(candidate)), 4),
                "development_p90": round(float(np.quantile(reference, 0.9)), 4),
                "blind_p90": round(float(np.quantile(candidate, 0.9)), 4),
                "psi": round(population_stability_index(reference, candidate), 4),
                "ks": round(kolmogorov_smirnov(reference, candidate), 4),
                "overlap_coefficient": round(
                    _overlap_coefficient(reference, candidate), 4
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("psi", ascending=False).reset_index(drop=True)
