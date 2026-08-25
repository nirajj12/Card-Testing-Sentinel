import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.features.batch import replay_partitioned_events
from card_testing_sentinel.v2.features.spec import (
    FORBIDDEN_FEATURE_TERMS,
    MODEL_FEATURES,
)


class DevelopmentDataValidationError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _device_weight(frame: pd.DataFrame) -> np.ndarray:
    counts = frame.groupby("device_id").device_id.transform("size")
    return (1 / counts).to_numpy()


def _training_sanity(
    features: pd.DataFrame, splits: pd.DataFrame, config: dict
) -> dict:
    train_devices = set(splits.loc[splits.split.eq("train"), "device_id"])
    train = features[features.device_id.isin(train_devices)].copy()
    train["fold"] = train.device_id.map(
        lambda value: int(hashlib.sha256(value.encode()).hexdigest(), 16) % 5
    )

    def grouped_oof(labels: pd.Series) -> tuple[np.ndarray, list[dict]]:
        predictions = np.zeros(len(train), dtype=float)
        fold_details = []
        for fold in range(5):
            fit_mask = train.fold.ne(fold)
            holdout_mask = ~fit_mask
            scaler = StandardScaler()
            fit_x = scaler.fit_transform(train.loc[fit_mask, MODEL_FEATURES])
            holdout_x = scaler.transform(train.loc[holdout_mask, MODEL_FEATURES])
            model = LogisticRegression(max_iter=300, random_state=20260825)
            model.fit(
                fit_x,
                labels.loc[fit_mask],
                sample_weight=_device_weight(train.loc[fit_mask]),
            )
            predictions[holdout_mask] = model.predict_proba(holdout_x)[:, 1]
            fit_devices = set(train.loc[fit_mask, "device_id"])
            holdout_devices = set(train.loc[holdout_mask, "device_id"])
            fold_details.append(
                {
                    "fold": fold,
                    "fit_devices": len(fit_devices),
                    "holdout_devices": len(holdout_devices),
                    "device_overlap": len(fit_devices & holdout_devices),
                }
            )
        return predictions, fold_details

    labels = train.label.astype(int)
    probability, fold_details = grouped_oof(labels)
    weights = _device_weight(train)
    precision, recall, thresholds = precision_recall_curve(
        labels, probability, sample_weight=weights
    )
    f1_values = (
        2
        * precision[:-1]
        * recall[:-1]
        / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    )
    threshold_index = int(np.argmax(f1_values))
    selected_threshold = float(thresholds[threshold_index])
    auc = roc_auc_score(labels, probability, sample_weight=weights)
    average_precision = average_precision_score(
        labels, probability, sample_weight=weights
    )
    weighted_f1 = f1_score(
        labels, probability >= selected_threshold, sample_weight=weights
    )
    for fold in fold_details:
        mask = train.fold.eq(fold["fold"])
        fold_weight = _device_weight(train.loc[mask])
        fold["roc_auc"] = float(
            roc_auc_score(
                labels.loc[mask], probability[mask], sample_weight=fold_weight
            )
        )
        fold["average_precision"] = float(
            average_precision_score(
                labels.loc[mask], probability[mask], sample_weight=fold_weight
            )
        )
        fold["f1"] = float(
            f1_score(
                labels.loc[mask],
                probability[mask] >= selected_threshold,
                sample_weight=fold_weight,
            )
        )

    device_labels = train[["device_id", "label"]].drop_duplicates("device_id")
    shuffled_values = device_labels.label.sample(
        frac=1, random_state=20260825
    ).to_numpy()
    shuffled_map = dict(zip(device_labels.device_id, shuffled_values, strict=True))
    shuffled_labels = train.device_id.map(shuffled_map).astype(int)
    shuffled_probability, shuffled_folds = grouped_oof(shuffled_labels)
    shuffled_auc = roc_auc_score(
        shuffled_labels, shuffled_probability, sample_weight=weights
    )

    best = {
        "feature": "",
        "direction": "",
        "threshold": 0.0,
        "weighted_f1": 0.0,
        "average_precision": 0.0,
    }
    for name in MODEL_FEATURES:
        values = train[name].to_numpy(dtype=float)
        for direction, scores in ((">=", values), ("<=", -values)):
            p, r, candidate_thresholds = precision_recall_curve(
                labels, scores, sample_weight=weights
            )
            candidate_f1 = 2 * p[:-1] * r[:-1] / np.maximum(p[:-1] + r[:-1], 1e-12)
            index = int(np.argmax(candidate_f1))
            score = float(candidate_f1[index])
            if score > best["weighted_f1"]:
                threshold = float(candidate_thresholds[index])
                best = {
                    "feature": name,
                    "direction": direction,
                    "threshold": threshold if direction == ">=" else -threshold,
                    "weighted_f1": score,
                    "average_precision": float(
                        average_precision_score(labels, scores, sample_weight=weights)
                    ),
                }
    correlations = train.loc[:, MODEL_FEATURES].corr().abs()
    pairs = [
        {
            "left": left,
            "right": right,
            "absolute_pearson": float(correlations.loc[left, right]),
        }
        for i, left in enumerate(MODEL_FEATURES)
        for right in MODEL_FEATURES[i + 1 :]
        if correlations.loc[left, right] >= config["high_correlation_threshold"]
    ]
    near_constant = [
        name for name in MODEL_FEATURES if train[name].nunique(dropna=False) <= 1
    ]
    return {
        "scope": "training-only data-quality diagnostic; not V2 model performance",
        "evaluation": "five-fold device-grouped out-of-fold on training devices only",
        "baseline_average_precision": float(average_precision),
        "baseline_roc_auc": float(auc),
        "baseline_f1": float(weighted_f1),
        "training_only_threshold": selected_threshold,
        "folds": fold_details,
        "shuffled_label_roc_auc": float(shuffled_auc),
        "shuffled_label_level": "device",
        "shuffled_fold_device_overlap": max(
            fold["device_overlap"] for fold in shuffled_folds
        ),
        "strongest_one_feature": best,
        "single_feature_search": (
            "all unique thresholds, both >= and <= directions, "
            "device weighted, training only"
        ),
        "near_constant_features": near_constant,
        "high_correlation_pairs": pairs,
        "passed": (
            config["sanity_baseline_min_roc_auc"]
            <= auc
            <= config["sanity_baseline_max_roc_auc"]
            and shuffled_auc <= config["shuffled_label_max_roc_auc"]
            and best["weighted_f1"] <= config["one_feature_max_f1"]
            and max(fold["device_overlap"] for fold in fold_details) == 0
            and not near_constant
        ),
    }


def _scenario_overlap_table(
    features: pd.DataFrame, raw: pd.DataFrame, splits: pd.DataFrame
) -> list[dict]:
    train_devices = splits.loc[splits.split.eq("train"), ["device_id", "scenario_tag"]]
    train = features.merge(
        train_devices[["device_id"]],
        on="device_id",
        how="inner",
        validate="many_to_one",
    )
    aggregations = {
        "processed_attempt_velocity_60s": ("prior_attempts_60s", "max"),
        "prospective_request_velocity_60s": ("prospective_requests_60s", "max"),
        "decline_ratio_24h": ("prior_decline_ratio_24h", "max"),
        "card_diversity_24h": ("distinct_cards_24h", "max"),
        "bin_diversity_24h": ("distinct_bins_24h", "max"),
        "same_card_retry_ratio_24h": ("same_card_retry_ratio_24h", "max"),
        "card_switches_after_decline_24h": (
            "card_switches_after_decline_24h",
            "max",
        ),
        "amount_continuity_absolute_delta": ("amount_delta_from_previous", "median"),
        "near_minimum_ratio_24h": ("near_minimum_ratio_24h", "max"),
        "session_count_7d": ("sessions_7d", "max"),
        "ip_rotation_24h": ("ip_changes_24h", "max"),
    }
    device_values = train_devices.copy().set_index("device_id")
    for metric, (column, operation) in aggregations.items():
        values = (
            train.assign(
                metric_value=train[column].abs()
                if metric == "amount_continuity_absolute_delta"
                else train[column]
            )
            .groupby("device_id")
            .metric_value.agg(operation)
        )
        device_values[metric] = values
    train_raw = raw.merge(
        train_devices[["device_id"]],
        on="device_id",
        how="inner",
        validate="many_to_one",
    )
    outcomes = train_raw.loc[train_raw.event_type.eq("authorization_outcome")]
    approval_rate = (
        outcomes.assign(
            approved=outcomes.authorization_result.eq("approved").astype(float)
        )
        .groupby("device_id")
        .approved.mean()
    )
    completions = (
        train_raw.loc[train_raw.event_type.eq("checkout_completion")]
        .groupby("device_id")
        .size()
        .gt(0)
        .astype(float)
    )
    device_values["approval_rate"] = approval_rate
    device_values["checkout_completion_rate"] = completions.reindex(
        device_values.index, fill_value=0
    )
    rows = []
    for scenario, group in device_values.groupby("scenario_tag", sort=True):
        for metric in [*aggregations, "approval_rate", "checkout_completion_rate"]:
            values = group[metric].astype(float)
            rows.append(
                {
                    "scenario": scenario,
                    "metric": metric,
                    "device_denominator": int(len(group)),
                    "mean": float(values.mean()),
                    "median": float(values.median()),
                    "p10": float(values.quantile(0.10)),
                    "p90": float(values.quantile(0.90)),
                    "minimum": float(values.min()),
                    "maximum": float(values.max()),
                }
            )
    return rows


def validate_bundle(root: Path) -> dict:
    data_dir = root / "data/v2/development"
    config = yaml.safe_load((root / "configs/v2/features.yaml").read_text())
    generation = yaml.safe_load((root / "configs/v2/generation.yaml").read_text())
    manifest = pd.read_json(data_dir / "manifest.json", typ="series").to_dict()
    raw = pd.read_csv(data_dir / "raw_events.csv")
    features = pd.read_csv(data_dir / "events_with_features.csv")
    splits = pd.read_csv(data_dir / "device_splits.csv")
    checks = {}

    def check(name: str, passed: bool, detail):
        checks[name] = {"passed": bool(passed), "detail": detail}

    check(
        "blind_test_absent",
        not any(root.glob("data/v2/**/*test*")),
        "train/validation only",
    )
    check(
        "split_values",
        set(splits.split) == {"train", "validation"},
        sorted(splits.split.unique()),
    )
    overlap = set(splits.loc[splits.split.eq("train"), "device_id"]) & set(
        splits.loc[splits.split.eq("validation"), "device_id"]
    )
    check("device_split_overlap", not overlap, len(overlap))
    observed_hashes = {
        name: _sha(data_dir / name)
        for name in ["raw_events.csv", "events_with_features.csv", "device_splits.csv"]
    }
    check("manifest_hashes", observed_hashes == manifest["sha256"], observed_hashes)
    check(
        "configuration_hashes",
        manifest["generation_config_sha256"]
        == _sha(root / "configs/v2/generation.yaml")
        and manifest["feature_contract_sha256"]
        == hashlib.sha256("\n".join(MODEL_FEATURES).encode()).hexdigest(),
        {
            "generation": manifest["generation_config_sha256"],
            "features": manifest["feature_contract_sha256"],
        },
    )
    check(
        "manifest_counts",
        len(raw) == manifest["counts"]["events"]
        and len(splits) == manifest["counts"]["devices"],
        manifest["counts"],
    )
    configured_counts = {
        key: int(value) for key, value in generation["device_counts"].items()
    }
    observed_counts = splits.scenario_tag.value_counts().sort_index().to_dict()
    check(
        "configured_scenario_counts",
        observed_counts == configured_counts,
        observed_counts,
    )
    timestamps = pd.to_datetime(raw.timestamp, utc=True, errors="coerce")
    check(
        "timestamps",
        timestamps.notna().all() and raw.event_sequence.is_unique,
        "UTC parse and unique sequence",
    )
    ordered = raw.assign(parsed=timestamps).sort_values(
        ["parsed", "event_sequence"], kind="mergesort"
    )
    check(
        "deterministic_order",
        ordered.event_id.tolist() == raw.event_id.tolist(),
        "timestamp then event_sequence",
    )
    forbidden_columns = {"pan", "cvv", "expiry", "raw_ip", "card_token"} & set(
        raw.columns
    )
    check("privacy_fields", not forbidden_columns, sorted(forbidden_columns))
    leaked_features = [
        name
        for name in MODEL_FEATURES
        if any(term in name for term in FORBIDDEN_FEATURE_TERMS)
    ]
    check("feature_allowlist_leakage", not leaked_features, leaked_features)
    outcome_columns = {"authorization_result", "decline_reason"} & set(features.columns)
    request_outcomes = raw.loc[
        raw.event_type.eq("authorization_request"),
        ["authorization_result", "decline_reason"],
    ]
    check(
        "outcomes_absent_at_precheck",
        not outcome_columns and request_outcomes.isna().all().all(),
        sorted(outcome_columns),
    )
    feature_values = features.loc[:, MODEL_FEATURES].to_numpy(dtype=float)
    check("finite_features", np.isfinite(feature_values).all(), feature_values.shape)
    request_count = int(raw.event_type.eq("authorization_request").sum())
    check(
        "one_row_per_precheck",
        len(features) == request_count,
        {"features": len(features), "requests": request_count},
    )
    mappings = raw.loc[
        raw.event_type.eq("authorization_request"), ["card_fingerprint", "card_bin"]
    ].drop_duplicates()
    check("stable_card_bin", mappings.card_fingerprint.is_unique, len(mappings))
    outcomes = raw.loc[raw.event_type.eq("authorization_outcome")]
    requests = raw.loc[
        raw.event_type.eq("authorization_request"), ["request_id", "timestamp"]
    ].rename(columns={"timestamp": "request_timestamp"})
    links = outcomes.merge(requests, on="request_id", how="left", validate="one_to_one")
    check(
        "request_outcome_linkage",
        links.request_timestamp.notna().all()
        and (
            pd.to_datetime(links.timestamp, utc=True)
            > pd.to_datetime(links.request_timestamp, utc=True)
        ).all(),
        len(links),
    )
    approved = outcomes.loc[
        outcomes.authorization_result.eq("approved"),
        ["request_id", "device_id", "session_id", "timestamp"],
    ].rename(columns={"timestamp": "approval_timestamp"})
    completions = raw.loc[
        raw.event_type.eq("checkout_completion"),
        ["request_id", "device_id", "session_id", "timestamp"],
    ]
    completion_links = completions.merge(
        approved,
        on=["request_id", "device_id", "session_id"],
        how="left",
        validate="one_to_one",
    )
    valid_completions = (
        completion_links.approval_timestamp.notna().all()
        and (
            pd.to_datetime(completion_links.timestamp, utc=True)
            > pd.to_datetime(completion_links.approval_timestamp, utc=True)
        ).all()
    )
    check("approval_completion_order", valid_completions, len(completions))
    legitimate = raw.loc[raw.label.eq(0)]
    completion_keys = completions.assign(
        completion_timestamp=pd.to_datetime(completions.timestamp, utc=True)
    )[["device_id", "session_id", "completion_timestamp"]]
    later_legitimate = legitimate.loc[
        legitimate.event_type.eq("authorization_request")
    ].assign(request_timestamp=lambda frame: pd.to_datetime(frame.timestamp, utc=True))
    after_completion = later_legitimate.merge(
        completion_keys, on=["device_id", "session_id"], how="inner"
    )
    check(
        "no_legitimate_request_after_completion",
        not (
            after_completion.request_timestamp > after_completion.completion_timestamp
        ).any(),
        int(
            (
                after_completion.request_timestamp
                > after_completion.completion_timestamp
            ).sum()
        ),
    )
    patient = raw.loc[
        raw.scenario_tag.eq("attack_patient")
        & raw.event_type.eq("authorization_request")
    ].assign(day=lambda frame: pd.to_datetime(frame.timestamp, utc=True).dt.date)
    patient_days = patient.groupby("device_id").day.nunique()
    check(
        "patient_sessions_separate_days",
        patient_days.ge(2).all(),
        patient_days.describe().to_dict(),
    )
    normal_requests = raw.loc[
        raw.population.eq("normal") & raw.event_type.eq("authorization_request")
    ].assign(parsed=lambda frame: pd.to_datetime(frame.timestamp, utc=True))
    normal_session_starts = (
        normal_requests.groupby(["device_id", "session_id"]).parsed.min().reset_index()
    )
    multi_normal = normal_session_starts.groupby("device_id").filter(
        lambda frame: len(frame) > 1
    )
    ordered_sessions = multi_normal.sort_values(["device_id", "parsed"])
    later_sessions = ordered_sessions.groupby("device_id").parsed.diff().dropna()
    check(
        "returning_normal_sessions_later",
        not later_sessions.empty and later_sessions.gt(pd.Timedelta(0)).all(),
        {"multi_session_devices": int(multi_normal.device_id.nunique())},
    )
    joined = raw.merge(splits[["device_id", "split"]], on="device_id", how="left")
    request_rows = joined.loc[joined.event_type.eq("authorization_request")]
    entity_overlap = {}
    for entity in ["card_fingerprint", "ip_fingerprint"]:
        train_entities = set(request_rows.loc[request_rows.split.eq("train"), entity])
        validation_entities = set(
            request_rows.loc[request_rows.split.eq("validation"), entity]
        )
        entity_overlap[entity] = len(train_entities & validation_entities)
    check(
        "entity_overlap_audit",
        entity_overlap["card_fingerprint"] == 0
        and entity_overlap["ip_fingerprint"] > 0,
        entity_overlap,
    )
    scenario_outcomes = (
        outcomes.groupby("scenario_tag")
        .authorization_result.value_counts()
        .unstack(fill_value=0)
    )
    overlap_ok = (scenario_outcomes.get("approved", 0) > 0).all() and (
        scenario_outcomes.get("declined", 0) > 0
    ).all()
    check("scenario_outcome_overlap", overlap_ok, scenario_outcomes.to_dict("index"))
    rebuilt = replay_partitioned_events(raw, splits)
    parity = rebuilt.event_id.tolist() == features.event_id.tolist() and np.allclose(
        rebuilt.loc[:, MODEL_FEATURES].to_numpy(dtype=float),
        features.loc[:, MODEL_FEATURES].to_numpy(dtype=float),
        atol=5e-7,
        rtol=0,
    )
    check("online_batch_parity", parity, len(rebuilt))
    subgroup_validation = (
        splits.loc[splits.split.eq("validation")].scenario_tag.value_counts().to_dict()
    )
    minimum = int(generation["minimum_validation_subgroup_devices"])
    check(
        "validation_subgroup_support",
        min(subgroup_validation.values()) >= minimum,
        subgroup_validation,
    )
    sanity = _training_sanity(features, splits, config)
    check("training_only_sanity", sanity["passed"], sanity)
    scenario_overlap = _scenario_overlap_table(features, raw, splits)
    overlap_scenarios = {row["scenario"] for row in scenario_overlap}
    check(
        "training_scenario_overlap_table",
        overlap_scenarios == set(generation["device_counts"]),
        {
            scenario: sum(
                row["device_denominator"]
                for row in scenario_overlap
                if row["scenario"] == scenario
            )
            // 13
            for scenario in sorted(overlap_scenarios)
        },
    )
    overlap_frame = pd.DataFrame(scenario_overlap)
    disjoint = []
    for metric, metric_rows in overlap_frame.groupby("metric"):
        for row in metric_rows.itertuples():
            others = metric_rows.loc[metric_rows.scenario.ne(row.scenario)]
            overlaps_another = (
                (others.minimum <= row.maximum) & (others.maximum >= row.minimum)
            ).any()
            if not overlaps_another:
                disjoint.append({"scenario": row.scenario, "metric": metric})
    check("no_deterministic_scenario_range", not disjoint, disjoint)
    passed = all(item["passed"] for item in checks.values())
    return {
        "status": "passed" if passed else "failed",
        "checks": checks,
        "sanity": sanity,
        "training_scenario_overlap": scenario_overlap,
    }


def write_validation_reports(root: Path) -> dict:
    report = validate_bundle(root)
    output = root / "artifacts/v2/data_quality/development_validation.json"
    atomic_write_json(output, report)
    lines = [
        "# V2 development data-quality report",
        "",
        f"Status: **{report['status']}**",
        "",
    ]
    lines.extend(
        f"- {name}: {'PASS' if result['passed'] else 'FAIL'} — {result['detail']}"
        for name, result in report["checks"].items()
    )
    atomic_write_text(
        root / "reports/v2/data_quality/development_validation.md",
        "\n".join(lines) + "\n",
    )
    atomic_write_text(
        root / "reports/v2/data_quality/training_scenario_overlap.csv",
        pd.DataFrame(report["training_scenario_overlap"]).to_csv(
            index=False, lineterminator="\n", float_format="%.6f"
        ),
    )
    if report["status"] != "passed":
        raise DevelopmentDataValidationError("V2 development validation failed")
    return report
