"""Dataset v3 gates.

Everything the standard validator already enforces is reused unchanged, so a
v2-to-v3 comparison cannot be an artifact of a redefined check. The gates
added here cover what v3 introduces: persistent customers, multi-device
customers, multi-episode histories, `customer_id` presence, and the two
bookkeeping defects found in Phases 6-7.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from card_testing_sentinel.ml.validation import (
    DatasetValidator,
    ValidationReport,
)

IDENTITY_COLUMNS = (
    "device_id",
    "customer_id",
    "session_id",
    "request_id",
    "event_id",
    "ip_fingerprint",
)


def _max_f1(values: np.ndarray, labels: np.ndarray) -> float:
    """Best F1 any single threshold on this one signal can reach."""
    best = 0.0
    positives = labels.sum()
    if positives == 0:
        return 0.0
    for threshold in np.unique(values):
        predicted = values >= threshold
        hits = float((predicted & (labels == 1)).sum())
        if hits == 0:
            continue
        precision = hits / float(predicted.sum())
        recall = hits / float(positives)
        best = max(best, 2 * precision * recall / (precision + recall))
    return float(best)


def check_label_bookkeeping(
    raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
) -> None:
    """Every labelled device must actually appear in the events.

    Blind v1.1 labelled 109 attack devices that never transacted, all from one
    family. A device that never made a request cannot be detected and is not
    a miss -- but it silently corrupts every denominator.
    """
    labelled = set(labels.device_id)
    transacting = set(raw.loc[raw.event_type.eq("authorization_request"), "device_id"])
    silent = labelled - transacting
    report.require(
        not silent,
        f"{len(silent)} labelled devices never transacted "
        f"(e.g. {sorted(silent)[:3]})",
    )
    orphan = transacting - labelled
    report.require(not orphan, f"{len(orphan)} transacting devices carry no label")
    report.summary["label_bookkeeping"] = {
        "labelled_devices": len(labelled),
        "transacting_devices": len(transacting),
        "silent_devices": len(silent),
    }


def check_merchant_realization(
    config: dict, labels: pd.DataFrame, report: ValidationReport
) -> None:
    """Every declared merchant kind must exist and carry devices."""
    declared = set(config["merchants"]["kinds"])
    realized = set(labels.merchant_kind)
    report.require(
        not declared - realized,
        f"declared merchant kinds absent from the data: {sorted(declared - realized)}",
    )
    devices = labels.drop_duplicates("device_id")
    per_kind = devices.groupby("merchant_kind").device_id.nunique().to_dict()
    thin = {kind: count for kind, count in per_kind.items() if count < 1}
    report.require(not thin, f"merchant kinds with no devices: {thin}")
    report.summary["merchant_realization"] = {
        "declared": sorted(declared),
        "realized": sorted(realized),
        "devices_per_kind": {str(k): int(v) for k, v in per_kind.items()},
    }


def check_customer_structure(
    gates: dict, labels: pd.DataFrame, report: ValidationReport
) -> None:
    """Multi-device customers must exist in BOTH populations.

    This is the anti-leakage gate that matters most in v3. If only attackers
    put several devices behind one customer, `customer_distinct_devices` is a
    relabelled label and Model v2's headline feature would be worthless.
    """
    spec = gates["multi_device_customers"]
    devices = labels.drop_duplicates("device_id")
    per_customer = devices.groupby("customer_id").agg(
        devices=("device_id", "nunique"), label=("label", "first")
    )
    multi = per_customer.loc[per_customer.devices > 1]
    counts = multi.groupby("label").size().to_dict()
    attack = int(counts.get(1, 0))
    legitimate = int(counts.get(0, 0))
    minimum = int(spec["min_per_population"])
    report.require(
        attack >= minimum and legitimate >= minimum,
        "multi-device customers must exist in both populations "
        f"(attack={attack}, legitimate={legitimate}, minimum={minimum})",
    )
    total = attack + legitimate
    share = max(attack, legitimate) / total if total else 1.0
    report.require(
        share <= float(spec["max_population_share"]),
        f"one population supplies {share:.2%} of multi-device customers; "
        f"the cap is {spec['max_population_share']:.0%}",
    )
    # A customer must never be both populations, and never cross a split.
    mixed = (
        devices.groupby("customer_id")
        .agg(labels=("label", "nunique"), splits=("split", "nunique"))
        .query("labels > 1 or splits > 1")
    )
    report.require(
        mixed.empty,
        f"{len(mixed)} customers span two labels or two splits",
    )
    report.summary["customer_structure"] = {
        "customers": int(per_customer.shape[0]),
        "multi_device_customers": total,
        "multi_device_attack": attack,
        "multi_device_legitimate": legitimate,
        "max_devices_per_customer": int(per_customer.devices.max()),
        "mean_devices_per_customer": round(float(per_customer.devices.mean()), 3),
    }


def check_customer_id_presence(
    gates: dict, raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
) -> None:
    """`customer_id_present` must not become a label shortcut."""
    spec = gates["customer_id_presence"]
    devices = labels.drop_duplicates("device_id")[["device_id", "label"]]
    requests = raw.loc[raw.event_type.eq("authorization_request")].merge(
        devices, on="device_id", how="left"
    )
    present = requests.customer_id.notna()
    overall = float(present.mean())
    attack = float(present.loc[requests.label.eq(1)].mean())
    legitimate = float(present.loc[requests.label.eq(0)].mean())
    gap = abs(attack - legitimate)

    report.require(
        float(spec["overall_min"]) <= overall <= float(spec["overall_max"]),
        f"customer_id present on {overall:.3f} of requests, outside the "
        f"declared band [{spec['overall_min']}, {spec['overall_max']}]",
    )
    report.require(
        gap <= float(spec["max_population_gap"]),
        f"customer_id presence differs by {gap:.3f} between populations "
        f"(attack {attack:.3f}, legitimate {legitimate:.3f}); the cap is "
        f"{spec['max_population_gap']}",
    )
    # Presence used alone as a classifier, both polarities.
    flag = present.to_numpy(dtype=float)
    truth = requests.label.to_numpy(dtype=int)
    single = max(_max_f1(flag, truth), _max_f1(1.0 - flag, truth))
    report.require(
        single <= float(spec["max_single_feature_f1"]),
        f"customer_id presence alone reaches F1 {single:.3f}; the cap is "
        f"{spec['max_single_feature_f1']}",
    )
    report.summary["customer_id_presence"] = {
        "overall": round(overall, 4),
        "attack": round(attack, 4),
        "legitimate": round(legitimate, 4),
        "population_gap": round(gap, 4),
        "single_feature_max_f1": round(single, 4),
    }


def check_long_horizon(
    gates: dict, raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
) -> None:
    """Both populations need devices whose activity spans several days.

    Without this the 7d/30d features Model v2 depends on would have nothing to
    measure, and a v2 ablation would "prove" long horizons are useless.
    """
    spec = gates["long_horizon"]
    requests = raw.loc[raw.event_type.eq("authorization_request")].copy()
    requests["ts"] = pd.to_datetime(requests.timestamp, format="ISO8601")
    span = requests.groupby("device_id").ts.agg(["min", "max"])
    span["days"] = (span["max"] - span["min"]).dt.total_seconds() / 86400.0
    devices = labels.drop_duplicates("device_id").set_index("device_id")
    span["label"] = devices.label
    span["scenario"] = devices.scenario

    minimum = float(spec["min_span_days"])
    floor = float(spec["min_device_share_per_population"])
    shares = {}
    for label, group in span.groupby("label"):
        share = float((group.days > minimum).mean())
        shares[int(label)] = round(share, 4)
        report.require(
            share >= floor,
            f"only {share:.2%} of {'attack' if label else 'legitimate'} devices "
            f"span more than {minimum} days; the floor is {floor:.0%}",
        )
    report.summary["long_horizon"] = {
        "min_span_days": minimum,
        "share_over_span": shares,
        "median_span_days": round(float(span.days.median()), 3),
        "p90_span_days": round(float(span.days.quantile(0.9)), 3),
        "max_span_days": round(float(span.days.max()), 3),
    }


def check_split_identity_separation(
    raw: pd.DataFrame, labels: pd.DataFrame, report: ValidationReport
) -> None:
    """No identifier of any kind may be shared across the two splits."""
    overlaps: dict[str, int] = {}
    for column in IDENTITY_COLUMNS:
        if column not in raw.columns:
            continue
        train = set(raw.loc[raw.split.eq("train"), column].dropna())
        validation = set(raw.loc[raw.split.eq("validation"), column].dropna())
        shared = train & validation
        overlaps[column] = len(shared)
        report.require(not shared, f"{len(shared)} {column}s reused across splits")
    label_overlap = set(labels.loc[labels.split.eq("train"), "customer_id"]) & set(
        labels.loc[labels.split.eq("validation"), "customer_id"]
    )
    report.require(not label_overlap, "customers reused across splits")
    overlaps["labelled_customer_id"] = len(label_overlap)
    report.summary["split_identity_overlap"] = overlaps


def validate_dataset_v3(
    config: dict,
    raw: pd.DataFrame,
    labels: pd.DataFrame,
    features: pd.DataFrame,
) -> ValidationReport:
    """Every gate Dataset v3 must clear before it is used for training."""
    gates = config["gates"]
    validator = DatasetValidator(gates)
    report = ValidationReport()

    validator.check_lifecycle(raw, report)
    validator.check_splits(labels, raw, report)
    validator.check_features(features, report)
    validator.check_univariate_leakage(features, report)
    validator.check_shuffled_labels(features, report)
    validator.check_overlap(features, report)
    validator.check_outcome_realism(raw, labels, report)
    validator.check_scenario_balance(raw, labels, report)

    check_label_bookkeeping(raw, labels, report)
    check_merchant_realization(config, labels, report)
    check_customer_structure(gates, labels, report)
    check_customer_id_presence(gates, raw, labels, report)
    check_long_horizon(gates, raw, labels, report)
    check_split_identity_separation(raw, labels, report)

    report.summary["eda"] = validator.describe(raw, labels, features)
    report.summary["model_trained"] = False
    return report
