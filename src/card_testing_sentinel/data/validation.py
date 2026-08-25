"""Executable contracts for the immutable synthetic v4 dataset."""

import hashlib
import json
import logging
import os
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from card_testing_sentinel.common.config import SentinelSettings
from card_testing_sentinel.common.exceptions import DataValidationError
from card_testing_sentinel.data.contracts import (
    ATTACK_SUBTYPES,
    DEVICE_SPLIT_COLUMNS,
    ENRICHED_EVENT_COLUMNS,
    EVENT_TYPES,
    POPULATIONS,
    RAW_EVENT_COLUMNS,
    SPLITS,
)
from card_testing_sentinel.data.loaders import load_frozen_bundle
from card_testing_sentinel.features.spec import (
    MODEL_FEATURES,
    validate_feature_contract,
)

logger = logging.getLogger(__name__)

NUMERIC_TOLERANCE = 1e-9
PROVENANCE_MEMBERS = (
    "generate_synthetic_data_v4.py",
    "compute_causal_features.py",
    "validate_dataset.py",
    "splitting.py",
    "feature_spec.py",
    "dataset_spec_v4.md",
    "CHECKSUMS.sha256",
    "README.md",
    "reports/validation_report.txt",
    "reports/plots/device_population_counts.png",
    "reports/plots/feature_distributions.png",
    "reports/plots/single_feature_strength.png",
    "data/raw_events.csv",
    "data/events_with_features.csv",
    "data/device_splits.csv",
)
CAUSAL_FEATURES = (
    "attempts_trailing_60s",
    "attempts_trailing_5min",
    "unique_cards_trailing_60s",
    "decline_ratio_so_far",
    "current_decline_streak",
    "attempts_before_first_approval",
    "attempts_this_session",
    "checkout_completed_so_far",
    "ip_device_count_trailing_5min",
)

COUNT_FEATURES = (
    "attempts_trailing_10s",
    "attempts_trailing_60s",
    "attempts_trailing_5min",
    "unique_cards_trailing_60s",
    "unique_cards_trailing_5min",
    "unique_bins_trailing_60s",
    "unique_bins_trailing_5min",
    "current_decline_streak",
    "attempts_before_first_approval",
    "cards_this_session",
    "attempts_this_session",
    "checkout_completed_so_far",
    "attempts_after_first_approval",
    "device_reuse_count",
    "ip_session_count_trailing_5min",
    "ip_device_count_trailing_5min",
)
RATIO_FEATURES = (
    "decline_ratio_so_far",
    "approval_ratio_so_far",
    "amount_near_minimum_ratio_5min",
    "repeated_amount_ratio",
    "unique_amount_ratio",
    "card_switch_rate",
)
NONNEGATIVE_CONTINUOUS_FEATURES = (
    "mean_interarrival_s",
    "var_interarrival_s",
    "amount_variance_so_far",
    "session_age_s",
)


@dataclass(frozen=True)
class ValidationCheck:
    """One stable, machine-readable validation outcome."""

    name: str
    passed: bool
    message: str
    observed: Any = None
    expected: Any = None


@dataclass(frozen=True)
class ValidationResult:
    """Complete validation result and deterministic report payload."""

    checks: tuple[ValidationCheck, ...]
    report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class _Recorder:
    def __init__(self) -> None:
        self.checks: list[ValidationCheck] = []

    def add(
        self,
        name: str,
        passed: bool,
        message: str,
        *,
        observed: Any = None,
        expected: Any = None,
    ) -> None:
        self.checks.append(
            ValidationCheck(name, bool(passed), message, observed, expected)
        )


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest without changing the file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_exact_columns(
    actual: tuple[str, ...], expected: tuple[str, ...], dataset_name: str
) -> ValidationCheck:
    """Check an exact frozen schema, including order and unexpected columns."""
    missing = [column for column in expected if column not in actual]
    unexpected = [column for column in actual if column not in expected]
    passed = actual == expected
    return ValidationCheck(
        name=f"schema.{dataset_name}.exact_columns",
        passed=passed,
        message=(
            "columns and order match the frozen contract"
            if passed
            else f"missing={missing}, unexpected={unexpected}, order_match={passed}"
        ),
        observed=list(actual),
        expected=list(expected),
    )


def validate_event_semantics(frame: pd.DataFrame) -> list[ValidationCheck]:
    """Validate event types and authorization/completion field semantics."""
    checks: list[ValidationCheck] = []
    observed_types = set(frame["event_type"].dropna().astype(str))
    checks.append(
        ValidationCheck(
            "semantics.allowed_event_types",
            observed_types == EVENT_TYPES,
            "event types must be exactly authorization and completion",
            sorted(observed_types),
            sorted(EVENT_TYPES),
        )
    )
    authorization = frame[frame["event_type"].eq("authorization")]
    completion = frame[frame["event_type"].eq("completion")]
    checks.append(
        ValidationCheck(
            "schema.timestamps_parsed",
            bool(
                pd.api.types.is_datetime64_any_dtype(frame["timestamp"])
                and frame["timestamp"].notna().all()
            ),
            "every event timestamp must parse deterministically",
        )
    )
    required = ("card_token", "card_bin", "amount", "declined")
    auth_present = bool(authorization.loc[:, required].notna().all().all())
    checks.append(
        ValidationCheck(
            "semantics.authorization_fields_present",
            auth_present,
            "authorization payment and outcome fields must be present",
        )
    )
    amounts = authorization["amount"].to_numpy(dtype=float)
    checks.append(
        ValidationCheck(
            "semantics.authorization_amounts_finite_positive",
            bool(np.isfinite(amounts).all() and (amounts > 0).all()),
            "authorization amounts must be finite and positive",
        )
    )
    declined = authorization["declined"].astype("boolean").fillna(False)
    reason_present = authorization["decline_reason"].notna()
    reason_valid = bool((declined == reason_present).all())
    checks.append(
        ValidationCheck(
            "semantics.decline_reason_matches_outcome",
            reason_valid,
            "decline reasons exist only for declined authorizations",
        )
    )
    completion_null = bool(
        completion.loc[:, (*required, "decline_reason")].isna().all().all()
    )
    checks.append(
        ValidationCheck(
            "semantics.completion_payment_fields_null",
            completion_null,
            "completion rows must retain null payment and outcome fields",
        )
    )
    return checks


def validate_event_identity(
    raw: pd.DataFrame, enriched: pd.DataFrame
) -> list[ValidationCheck]:
    """Validate unique IDs and exact cross-file event membership."""
    return [
        ValidationCheck(
            "identity.raw_event_ids_unique",
            bool(raw["event_id"].is_unique),
            "raw event IDs must be unique",
        ),
        ValidationCheck(
            "identity.enriched_event_ids_unique",
            bool(enriched["event_id"].is_unique),
            "enriched event IDs must be unique",
        ),
        ValidationCheck(
            "identity.raw_enriched_event_ids_match",
            set(raw["event_id"]) == set(enriched["event_id"]),
            "raw and enriched files must contain identical event IDs",
        ),
    ]


def validate_entity_contracts(frame: pd.DataFrame) -> list[ValidationCheck]:
    """Validate stable device/session metadata and token ownership."""
    checks: list[ValidationCheck] = []

    def stable(group: str, column: str) -> bool:
        return bool(frame.groupby(group)[column].nunique(dropna=False).le(1).all())

    for column in ("population", "attack_subtype", "entity_label"):
        checks.append(
            ValidationCheck(
                f"entity.device_stable_{column}",
                stable("device_id", column),
                f"{column} must be stable within each device",
            )
        )
    for column in ("device_id", "scenario_tag"):
        checks.append(
            ValidationCheck(
                f"entity.session_stable_{column}",
                stable("session_id", column),
                f"{column} must be stable within each session",
            )
        )

    authorization = frame[frame["event_type"].eq("authorization")]
    token_stable = bool(
        authorization.groupby("card_token")["card_bin"]
        .nunique(dropna=False)
        .le(1)
        .all()
    )
    checks.append(
        ValidationCheck(
            "entity.card_token_maps_to_one_bin",
            token_stable,
            "each card token must map to one normalized BIN",
        )
    )

    observed_populations = set(frame["population"].dropna().astype(str))
    checks.append(
        ValidationCheck(
            "entity.allowed_populations",
            observed_populations == POPULATIONS,
            "population values must match the frozen categories",
            sorted(observed_populations),
            sorted(POPULATIONS),
        )
    )
    attack = frame["population"].eq("attack")
    subtype_valid = bool(
        frame.loc[attack, "attack_subtype"].isin(ATTACK_SUBTYPES).all()
        and frame.loc[~attack, "attack_subtype"].isna().all()
    )
    checks.append(
        ValidationCheck(
            "entity.attack_subtype_semantics",
            subtype_valid,
            "subtype is required for attacks and blank for legitimate populations",
        )
    )
    label_valid = bool(
        frame["entity_label"].isin([0, 1]).all()
        and frame["entity_label"].eq(1).eq(attack).all()
    )
    checks.append(
        ValidationCheck(
            "entity.label_matches_population",
            label_valid,
            "label must be binary and equal one exactly for attack rows",
        )
    )
    return checks


def validate_feature_domains(frame: pd.DataFrame) -> list[ValidationCheck]:
    """Validate finite values and domain relationships for all 26 features."""
    checks: list[ValidationCheck] = []
    matrix = frame.loc[:, MODEL_FEATURES].to_numpy(dtype=float)
    checks.append(
        ValidationCheck(
            "features.all_finite_and_present",
            bool(np.isfinite(matrix).all()),
            "allowlisted features must contain no NaN or infinity",
        )
    )
    count_values = frame.loc[:, COUNT_FEATURES].to_numpy(dtype=float)
    checks.append(
        ValidationCheck(
            "features.counts_nonnegative_whole_numbers",
            bool(
                (count_values >= -NUMERIC_TOLERANCE).all()
                and np.isclose(
                    count_values,
                    np.rint(count_values),
                    rtol=0,
                    atol=NUMERIC_TOLERANCE,
                ).all()
            ),
            "count features must be non-negative whole numbers",
        )
    )
    ratio_values = frame.loc[:, RATIO_FEATURES].to_numpy(dtype=float)
    checks.append(
        ValidationCheck(
            "features.ratios_in_unit_interval",
            bool(
                (ratio_values >= -NUMERIC_TOLERANCE).all()
                and (ratio_values <= 1 + NUMERIC_TOLERANCE).all()
            ),
            "ratio features must lie within [0, 1]",
        )
    )
    continuous = frame.loc[:, NONNEGATIVE_CONTINUOUS_FEATURES].to_numpy(dtype=float)
    checks.append(
        ValidationCheck(
            "features.durations_and_variances_nonnegative",
            bool((continuous >= -NUMERIC_TOLERANCE).all()),
            "duration, inter-arrival, and variance features must be non-negative",
        )
    )
    ratio_sum = frame["decline_ratio_so_far"] + frame["approval_ratio_so_far"]
    has_history = ratio_sum > NUMERIC_TOLERANCE
    checks.append(
        ValidationCheck(
            "features.decline_approval_ratios_complementary",
            bool(
                np.isclose(
                    ratio_sum[has_history],
                    1.0,
                    rtol=0,
                    atol=NUMERIC_TOLERANCE,
                ).all()
            ),
            "decline and approval ratios must sum to one after observed history",
        )
    )
    relationships = {
        "features.unique_cards_60s_within_attempts": (
            frame["unique_cards_trailing_60s"] <= frame["attempts_trailing_60s"]
        ),
        "features.unique_cards_5min_within_attempts": (
            frame["unique_cards_trailing_5min"] <= frame["attempts_trailing_5min"]
        ),
        "features.unique_bins_60s_within_attempts": (
            frame["unique_bins_trailing_60s"] <= frame["attempts_trailing_60s"]
        ),
        "features.unique_bins_5min_within_attempts": (
            frame["unique_bins_trailing_5min"] <= frame["attempts_trailing_5min"]
        ),
        "features.session_cards_within_attempts": (
            frame["cards_this_session"] <= frame["attempts_this_session"]
        ),
        "features.ip_devices_within_sessions": (
            frame["ip_device_count_trailing_5min"]
            <= frame["ip_session_count_trailing_5min"]
        ),
        "features.checkout_state_binary": frame["checkout_completed_so_far"].isin(
            [0, 1]
        ),
    }
    for name, condition in relationships.items():
        checks.append(
            ValidationCheck(name, bool(condition.all()), "feature relationship holds")
        )
    return checks


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(["timestamp", "event_sequence"], kind="stable")


def _device_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        _ordered(frame)
        .groupby("device_id", as_index=False)
        .first()[["device_id", "population", "attack_subtype", "entity_label"]]
    )


def scenario_counts(frame: pd.DataFrame) -> tuple[dict[str, int], dict[str, int]]:
    """Return session counts and overlapping distinct-device memberships."""
    session_meta = (
        _ordered(frame)
        .groupby("session_id", as_index=False)
        .first()[["session_id", "device_id", "scenario_tag"]]
    )
    sessions = {
        str(key): int(value)
        for key, value in session_meta["scenario_tag"]
        .value_counts()
        .sort_index()
        .items()
    }
    memberships = session_meta[["device_id", "scenario_tag"]].drop_duplicates()
    devices = {
        str(key): int(value)
        for key, value in memberships.groupby("scenario_tag")["device_id"]
        .nunique()
        .sort_index()
        .items()
    }
    return sessions, devices


def normal_scenario_membership(frame: pd.DataFrame) -> dict[str, int]:
    """Return mutually exclusive normal-device scenario memberships."""
    normal = frame[frame["population"].eq("normal")]
    session_meta = (
        _ordered(normal)
        .groupby("session_id", as_index=False)
        .first()[["session_id", "device_id", "scenario_tag"]]
    )
    by_device = session_meta.groupby("device_id")["scenario_tag"].agg(set)
    standard = "normal_standard"
    bad_luck = "normal_bad_luck"
    return {
        "bad_luck_only": int(by_device.map(lambda values: values == {bad_luck}).sum()),
        "both": int(by_device.map(lambda values: {standard, bad_luck} <= values).sum()),
        "returning_with_second_session": int(
            session_meta.groupby("device_id")["session_id"].nunique().ge(2).sum()
        ),
        "standard_only": int(by_device.map(lambda values: values == {standard}).sum()),
        "total_normal_devices": int(session_meta["device_id"].nunique()),
        "total_normal_sessions": int(session_meta["session_id"].nunique()),
    }


def validate_split_integrity(
    raw: pd.DataFrame, splits: pd.DataFrame
) -> list[ValidationCheck]:
    """Validate one frozen, disjoint device assignment and group ownership."""
    checks: list[ValidationCheck] = []
    checks.append(
        ValidationCheck(
            "splits.one_row_per_device",
            bool(splits["device_id"].notna().all() and splits["device_id"].is_unique),
            "each split device must appear exactly once",
        )
    )
    observed_splits = set(splits["split"].dropna().astype(str))
    checks.append(
        ValidationCheck(
            "splits.allowed_values",
            observed_splits == SPLITS,
            "split values must be exactly train, validation, and test",
            sorted(observed_splits),
            sorted(SPLITS),
        )
    )
    event_devices = set(raw["device_id"].dropna().astype(str))
    split_devices = set(splits["device_id"].dropna().astype(str))
    checks.append(
        ValidationCheck(
            "splits.complete_device_membership",
            event_devices == split_devices,
            "split devices must exactly match event devices",
            {
                "missing": len(event_devices - split_devices),
                "extra": len(split_devices - event_devices),
            },
            {"missing": 0, "extra": 0},
        )
    )
    split_sets = {
        name: set(splits.loc[splits["split"].eq(name), "device_id"].astype(str))
        for name in SPLITS
    }
    overlap = (
        (split_sets["train"] & split_sets["validation"])
        | (split_sets["train"] & split_sets["test"])
        | (split_sets["validation"] & split_sets["test"])
    )
    checks.append(
        ValidationCheck(
            "splits.pairwise_disjoint",
            not overlap,
            "train, validation, and test device sets must be disjoint",
            len(overlap),
            0,
        )
    )
    device_meta = _device_metadata(raw)
    expected_group = device_meta["population"].astype(str)
    attack = device_meta["population"].eq("attack")
    expected_group.loc[attack] = device_meta.loc[attack, "attack_subtype"].astype(str)
    group_map = dict(
        zip(device_meta["device_id"].astype(str), expected_group, strict=True)
    )
    actual_group = splits["device_id"].astype(str).map(group_map)
    checks.append(
        ValidationCheck(
            "splits.group_matches_device_metadata",
            bool(actual_group.notna().all() and actual_group.eq(splits["group"]).all()),
            "split group must match population or attacker subtype",
        )
    )
    session_meta = (
        _ordered(raw)
        .groupby("session_id", as_index=False)
        .first()[["device_id", "scenario_tag"]]
        .drop_duplicates()
    )
    scenario_split = session_meta.merge(
        splits[["device_id", "split"]], on="device_id", how="left"
    )
    represented = (
        scenario_split.groupby(["scenario_tag", "split"]).size().unstack(fill_value=0)
    )
    represented = represented.reindex(columns=sorted(SPLITS), fill_value=0)
    checks.append(
        ValidationCheck(
            "splits.every_scenario_represented",
            bool((represented > 0).all().all()),
            "every session scenario must occur in every split",
        )
    )
    return checks


def _semantic_base_fields_match(raw: pd.DataFrame, enriched: pd.DataFrame) -> bool:
    left = raw.sort_values("event_id").reset_index(drop=True)
    right = enriched.sort_values("event_id").reset_index(drop=True)
    if len(left) != len(right) or not left["event_id"].equals(right["event_id"]):
        return False
    for column in RAW_EVENT_COLUMNS:
        if column == "amount":
            if not np.isclose(
                left[column].to_numpy(dtype=float, na_value=np.nan),
                right[column].to_numpy(dtype=float, na_value=np.nan),
                rtol=0,
                atol=NUMERIC_TOLERANCE,
                equal_nan=True,
            ).all():
                return False
        elif column == "timestamp":
            if not left[column].equals(right[column]):
                return False
        else:
            left_values = left[column].astype("string").fillna("<NULL>")
            right_values = right[column].astype("string").fillna("<NULL>")
            if not left_values.equals(right_values):
                return False
    return True


def _completion_state_checks(frame: pd.DataFrame) -> tuple[list[ValidationCheck], int]:
    ordered = _ordered(frame).reset_index(drop=True).copy()
    ordered["_position"] = np.arange(len(ordered))
    is_completion = ordered["event_type"].eq("completion")
    is_authorization = ordered["event_type"].eq("authorization")
    is_approval = is_authorization & ordered["declined"].eq(False).fillna(False)

    first_device_completion = (
        ordered.loc[is_completion].groupby("device_id")["_position"].min()
    )
    device_completion_position = ordered["device_id"].map(first_device_completion)
    expected_state = (
        device_completion_position.notna()
        & ordered["_position"].ge(device_completion_position)
    ).astype(int)
    state_matches = bool(
        ordered["checkout_completed_so_far"].astype(int).eq(expected_state).all()
    )

    approvals_so_far = is_approval.astype(int).groupby(ordered["session_id"]).cumsum()
    completion_without_approval = int((is_completion & approvals_so_far.eq(0)).sum())

    first_session_completion = (
        ordered.loc[is_completion].groupby("session_id")["_position"].min()
    )
    session_completion_position = ordered["session_id"].map(first_session_completion)
    after_completion = is_authorization & ordered["_position"].gt(
        session_completion_position
    )
    post_completion = {
        str(key): int(value)
        for key, value in ordered.loc[after_completion, "population"]
        .value_counts()
        .items()
    }

    legitimate = sum(
        value
        for key, value in post_completion.items()
        if key in {"normal", "flash_sale"}
    )
    attack_count = post_completion.get("attack", 0)
    checks = [
        ValidationCheck(
            "causality.checkout_state_matches_prior_completions",
            state_matches,
            "completion state changes on completion and remains visible later",
        ),
        ValidationCheck(
            "causality.every_completion_follows_approval",
            completion_without_approval == 0,
            "every completion must follow an approved authorization",
            completion_without_approval,
            0,
        ),
        ValidationCheck(
            "causality.no_legitimate_authorization_after_session_completion",
            legitimate == 0,
            "normal and flash-sale sessions stop authorizing after completion",
            legitimate,
            0,
        ),
    ]
    return checks, attack_count


def _as_bool(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise DataValidationError("authorization outcome is not boolean")


def _causal_history(raw: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    return raw[
        (raw["timestamp"] < row["timestamp"])
        | (
            raw["timestamp"].eq(row["timestamp"])
            & raw["event_sequence"].le(row["event_sequence"])
        )
    ]


def _manual_causal_snapshot(row: pd.Series, raw: pd.DataFrame) -> dict[str, float]:
    causal = _causal_history(raw, row)
    device = _ordered(causal[causal["device_id"].eq(row["device_id"])])
    authorizations = device[device["event_type"].eq("authorization")]
    session = authorizations[authorizations["session_id"].eq(row["session_id"])]
    trailing_60s = authorizations[
        authorizations["timestamp"] > row["timestamp"] - pd.Timedelta(seconds=60)
    ]
    trailing_5min = authorizations[
        authorizations["timestamp"] > row["timestamp"] - pd.Timedelta(minutes=5)
    ]
    declined = [_as_bool(value) for value in authorizations["declined"]]
    streak = 0
    for value in reversed(declined):
        if not value:
            break
        streak += 1
    approvals = [index for index, value in enumerate(declined, start=1) if not value]
    attempts_before_approval = approvals[0] - 1 if approvals else len(declined)
    ip_authorizations = causal[
        causal["event_type"].eq("authorization")
        & causal["ip_hash"].eq(row["ip_hash"])
        & (causal["timestamp"] > row["timestamp"] - pd.Timedelta(minutes=5))
    ]
    return {
        "attempts_trailing_60s": float(len(trailing_60s)),
        "attempts_trailing_5min": float(len(trailing_5min)),
        "unique_cards_trailing_60s": float(trailing_60s["card_token"].nunique()),
        "decline_ratio_so_far": float(np.mean(declined)) if declined else 0.0,
        "current_decline_streak": float(streak),
        "attempts_before_first_approval": float(attempts_before_approval),
        "attempts_this_session": float(len(session)),
        "checkout_completed_so_far": float(device["event_type"].eq("completion").any()),
        "ip_device_count_trailing_5min": float(
            ip_authorizations["device_id"].nunique()
        ),
    }


def _select_causal_sample(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    ordered = _ordered(raw).reset_index(drop=True)
    authorization = ordered[ordered["event_type"].eq("authorization")]
    selected: list[str] = []
    categories: list[str] = []

    def add(category: str, candidates: pd.DataFrame) -> None:
        available = candidates[~candidates["event_id"].isin(selected)]
        choice = available.iloc[0] if not available.empty else candidates.iloc[0]
        selected.append(str(choice["event_id"]))
        categories.append(category)

    first_device_auth = authorization[
        authorization.groupby("device_id").cumcount().eq(0)
    ]
    add("first_authorization_of_device", first_device_auth)
    repeated = authorization[authorization.groupby("session_id").cumcount().ge(1)]
    add("repeated_authorization_in_session", repeated)
    add("completion_event", ordered[ordered["event_type"].eq("completion")])

    ordered["_position"] = np.arange(len(ordered))
    completion = ordered[ordered["event_type"].eq("completion")]
    first_completion = completion.groupby("session_id")["_position"].min()
    completion_position = ordered["session_id"].map(first_completion)
    after_completion_ids = ordered.loc[
        ordered["event_type"].eq("authorization")
        & ordered["population"].eq("attack")
        & ordered["_position"].gt(completion_position),
        "event_id",
    ].astype(str)
    add(
        "attack_authorization_after_completion",
        ordered[ordered["event_id"].isin(after_completion_ids)],
    )

    shared_flash_ids: list[str] = []
    histories: dict[str, list[tuple[pd.Timestamp, str]]] = {}
    for row in authorization.itertuples(index=False):
        ip_hash = str(row.ip_hash)
        cutoff = row.timestamp - pd.Timedelta(minutes=5)
        recent = [item for item in histories.get(ip_hash, []) if item[0] > cutoff]
        recent.append((row.timestamp, str(row.device_id)))
        histories[ip_hash] = recent
        if row.population == "flash_sale" and len({item[1] for item in recent}) > 1:
            shared_flash_ids.append(str(row.event_id))
    add(
        "shared_ip_flash_sale",
        authorization[authorization["event_id"].isin(shared_flash_ids)],
    )
    for subtype in ("burst", "evasive", "patient"):
        add(
            f"attacker_subtype_{subtype}",
            authorization[authorization["attack_subtype"].eq(subtype)],
        )
    add(
        "normal_bad_luck",
        authorization[authorization["scenario_tag"].eq("normal_bad_luck")],
    )
    add(
        "flash_hard_retry",
        authorization[authorization["scenario_tag"].eq("flash_hard_retry")],
    )
    sample = ordered[ordered["event_id"].isin(selected)].copy()
    sample["event_id"] = pd.Categorical(
        sample["event_id"], categories=selected, ordered=True
    )
    sample = sample.sort_values("event_id").reset_index(drop=True)
    sample["event_id"] = sample["event_id"].astype("string")
    return sample, categories


def _causal_recomputation_checks(
    raw: pd.DataFrame, enriched: pd.DataFrame
) -> tuple[list[ValidationCheck], int, list[str]]:
    sample, categories = _select_causal_sample(raw)
    enriched_by_id = enriched.set_index("event_id")
    mismatches = {feature: 0 for feature in CAUSAL_FEATURES}
    for _, raw_row in sample.iterrows():
        expected = _manual_causal_snapshot(raw_row, raw)
        actual = enriched_by_id.loc[str(raw_row["event_id"])]
        for feature in CAUSAL_FEATURES:
            if feature == "decline_ratio_so_far":
                matches = np.isclose(
                    float(actual[feature]),
                    expected[feature],
                    rtol=0,
                    atol=NUMERIC_TOLERANCE,
                )
            else:
                matches = float(actual[feature]) == expected[feature]
            if not matches:
                mismatches[feature] += 1
    checks = [
        ValidationCheck(
            "causal_sample.required_coverage",
            len(categories) == 10,
            "deterministic sample covers all required behavioral cases",
            categories,
            [
                "first_authorization_of_device",
                "repeated_authorization_in_session",
                "completion_event",
                "attack_authorization_after_completion",
                "shared_ip_flash_sale",
                "attacker_subtype_burst",
                "attacker_subtype_evasive",
                "attacker_subtype_patient",
                "normal_bad_luck",
                "flash_hard_retry",
            ],
        )
    ]
    for feature in CAUSAL_FEATURES:
        checks.append(
            ValidationCheck(
                f"causal_recomputation.{feature}",
                mismatches[feature] == 0,
                "independent raw-history recomputation matches frozen feature",
                {
                    "matched": len(sample) - mismatches[feature],
                    "sample_size": len(sample),
                },
                {"matched": len(sample), "sample_size": len(sample)},
            )
        )
    return checks, len(sample), list(CAUSAL_FEATURES)


def _archive_checks(
    settings: SentinelSettings, manifest: dict[str, Any]
) -> tuple[list[ValidationCheck], dict[str, Any]]:
    archive = settings.frozen_dataset.archive_path
    expected_archive = manifest["provenance_archive"]["sha256"]
    actual_archive = sha256_file(archive) if archive.is_file() else None
    checks = [
        ValidationCheck(
            "integrity.provenance_archive_sha256",
            actual_archive == expected_archive,
            "provenance archive checksum matches",
            actual_archive,
            expected_archive,
        )
    ]
    required_verified = False
    internal_matches: dict[str, bool] = {}
    if actual_archive == expected_archive:
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            required_verified = set(PROVENANCE_MEMBERS).issubset(names)
            for filename, metadata in manifest["files"].items():
                member = f"data/{filename}"
                digest = hashlib.sha256(bundle.read(member)).hexdigest()
                internal_matches[filename] = digest == metadata["sha256"]
    checks.append(
        ValidationCheck(
            "integrity.provenance_required_contents",
            required_verified,
            "archive contains specification, scripts, reports, plots, and CSVs",
        )
    )
    checks.append(
        ValidationCheck(
            "integrity.archive_csvs_match_manifest",
            bool(internal_matches) and all(internal_matches.values()),
            "all internal CSV bytes match the frozen manifest",
            internal_matches,
            {filename: True for filename in manifest["files"]},
        )
    )
    return checks, {
        "checksum": actual_archive,
        "required_contents_verified": required_verified,
        "internal_csv_provenance": internal_matches,
    }


def _record_expected_map(
    recorder: _Recorder, name: str, observed: dict[str, Any], expected: dict[str, Any]
) -> None:
    recorder.add(
        name,
        observed == expected,
        "observed counts match the frozen manifest",
        observed=observed,
        expected=expected,
    )


def inspect_frozen_dataset(settings: SentinelSettings) -> ValidationResult:
    """Run every frozen-data check without fitting or evaluating a model."""
    logger.info("Starting frozen dataset validation")
    validate_feature_contract(ENRICHED_EVENT_COLUMNS)
    bundle = load_frozen_bundle(settings)
    raw = bundle.raw_events
    enriched = bundle.enriched_events
    splits = bundle.device_splits
    manifest = bundle.manifest
    expected = manifest["expected_counts"]
    recorder = _Recorder()

    recorder.add(
        "manifest.dataset_version",
        manifest.get("dataset_version") == settings.frozen_dataset.version,
        "manifest version matches configured frozen dataset version",
        observed=manifest.get("dataset_version"),
        expected=settings.frozen_dataset.version,
    )
    recorder.checks.extend(
        [
            check_exact_columns(tuple(raw.columns), RAW_EVENT_COLUMNS, "raw_events"),
            check_exact_columns(
                tuple(enriched.columns), ENRICHED_EVENT_COLUMNS, "enriched_events"
            ),
            check_exact_columns(
                tuple(splits.columns), DEVICE_SPLIT_COLUMNS, "device_splits"
            ),
        ]
    )

    frozen_dir = settings.paths.frozen_data
    configured_filenames = {
        settings.frozen_dataset.raw_events_filename,
        settings.frozen_dataset.enriched_events_filename,
        settings.frozen_dataset.device_splits_filename,
    }
    recorder.add(
        "integrity.filenames_match_contract",
        configured_filenames == set(manifest["files"]),
        "configured frozen filenames must exactly match the manifest",
        observed=sorted(configured_filenames),
        expected=sorted(manifest["files"]),
    )
    loaded_rows = {
        settings.frozen_dataset.raw_events_filename: len(raw),
        settings.frozen_dataset.enriched_events_filename: len(enriched),
        settings.frozen_dataset.device_splits_filename: len(splits),
    }
    file_checksums: dict[str, str] = {}
    for filename, metadata in manifest["files"].items():
        path = frozen_dir / filename
        recorder.add(
            f"integrity.{filename}.regular_file",
            path.is_file(),
            "frozen artifact must exist as a regular file",
        )
        actual = sha256_file(path)
        file_checksums[filename] = actual
        recorder.add(
            f"integrity.{filename}.sha256",
            actual == metadata["sha256"],
            "destination checksum matches frozen manifest",
            observed=actual,
            expected=metadata["sha256"],
        )
        recorder.add(
            f"integrity.{filename}.row_count",
            loaded_rows[filename] == metadata["expected_rows"],
            "CSV data-row count matches the manifest",
            observed=loaded_rows[filename],
            expected=metadata["expected_rows"],
        )
    archive_checks, archive_report = _archive_checks(settings, manifest)
    recorder.checks.extend(archive_checks)

    recorder.checks.extend(validate_event_identity(raw, enriched))
    sequences = raw["event_sequence"].to_numpy(dtype=float)
    expected_sequences = np.arange(1, expected["event_rows"] + 1)
    recorder.add(
        "ordering.event_sequence_complete_unique_range",
        bool(
            raw["event_sequence"].is_unique
            and np.array_equal(np.sort(sequences), expected_sequences)
        ),
        "event sequence must uniquely cover one through total event rows",
    )
    recorder.add(
        "ordering.global_timestamp_nondecreasing",
        bool(raw["timestamp"].is_monotonic_increasing),
        "CSV rows must be globally non-decreasing by timestamp",
    )
    stable_order = _ordered(raw).index.to_list() == raw.index.to_list()
    recorder.add(
        "ordering.timestamp_ties_use_event_sequence",
        stable_order,
        "timestamp ties must be ordered by event_sequence",
    )
    previous_timestamp = raw.groupby("device_id", sort=False)["timestamp"].shift()
    previous_sequence = raw.groupby("device_id", sort=False)["event_sequence"].shift()
    device_order = bool(
        (
            previous_timestamp.isna()
            | raw["timestamp"].gt(previous_timestamp)
            | (
                raw["timestamp"].eq(previous_timestamp)
                & raw["event_sequence"].ge(previous_sequence)
            )
        ).all()
    )
    recorder.add(
        "ordering.device_history_nondecreasing",
        device_order,
        "device histories must follow timestamp and event_sequence tie-breaking",
    )

    recorder.checks.extend(validate_event_semantics(raw))
    recorder.checks.extend(validate_entity_contracts(raw))
    recorder.add(
        "consistency.raw_enriched_base_fields_match",
        _semantic_base_fields_match(raw, enriched),
        "all 16 base fields must agree after in-memory normalization",
    )
    recorder.checks.extend(validate_feature_domains(enriched))
    completion_checks, attack_after_completion = _completion_state_checks(enriched)
    recorder.checks.extend(completion_checks)
    recorder.add(
        "causality.attack_authorizations_after_session_completion",
        attack_after_completion
        == expected["attack_authorizations_after_same_session_completion"],
        "intentional attacker continuation count must be preserved",
        observed=attack_after_completion,
        expected=expected["attack_authorizations_after_same_session_completion"],
    )
    recorder.checks.extend(validate_split_integrity(raw, splits))

    event_counts = {
        "authorization_rows": int(raw["event_type"].eq("authorization").sum()),
        "completion_rows": int(raw["event_type"].eq("completion").sum()),
        "devices": int(raw["device_id"].nunique()),
        "event_rows": int(len(raw)),
        "model_features": len(MODEL_FEATURES),
        "sessions": int(raw["session_id"].nunique()),
    }
    for key, observed in event_counts.items():
        recorder.add(
            f"counts.{key}",
            observed == expected[key],
            f"{key} matches the frozen manifest",
            observed=observed,
            expected=expected[key],
        )

    device_meta = _device_metadata(raw)
    population_counts = {
        str(key): int(value)
        for key, value in device_meta["population"].value_counts().sort_index().items()
    }
    subtype_counts = {
        str(key): int(value)
        for key, value in device_meta.loc[
            device_meta["population"].eq("attack"), "attack_subtype"
        ]
        .value_counts()
        .sort_index()
        .items()
    }
    label_counts = {
        str(int(key)): int(value)
        for key, value in device_meta["entity_label"]
        .value_counts()
        .sort_index()
        .items()
    }
    sessions_by_scenario, devices_by_scenario = scenario_counts(raw)
    normal_membership = normal_scenario_membership(raw)
    split_counts = {
        str(key): int(value)
        for key, value in splits["split"].value_counts().sort_index().items()
    }
    split_group_counts = {
        str(group): {
            str(split): int(value)
            for split, value in group_frame["split"].value_counts().sort_index().items()
        }
        for group, group_frame in splits.groupby("group", sort=True)
    }
    _record_expected_map(
        recorder,
        "counts.devices_by_population",
        population_counts,
        expected["devices_by_population"],
    )
    _record_expected_map(
        recorder,
        "counts.attacker_devices_by_subtype",
        subtype_counts,
        expected["attacker_devices_by_subtype"],
    )
    _record_expected_map(
        recorder, "counts.devices_by_label", label_counts, expected["devices_by_label"]
    )
    _record_expected_map(
        recorder,
        "counts.sessions_by_scenario",
        sessions_by_scenario,
        expected["sessions_by_scenario"],
    )
    _record_expected_map(
        recorder,
        "counts.distinct_devices_ever_tagged_by_scenario",
        devices_by_scenario,
        expected["distinct_devices_ever_tagged_by_scenario"],
    )
    _record_expected_map(
        recorder,
        "counts.normal_device_scenario_membership",
        normal_membership,
        expected["normal_device_scenario_membership"],
    )
    _record_expected_map(
        recorder, "counts.devices_by_split", split_counts, expected["devices_by_split"]
    )
    _record_expected_map(
        recorder,
        "counts.devices_by_group_and_split",
        split_group_counts,
        expected["devices_by_group_and_split"],
    )

    causal_checks, sample_size, causal_features = _causal_recomputation_checks(
        raw, enriched
    )
    recorder.checks.extend(causal_checks)

    passed_count = sum(check.passed for check in recorder.checks)
    failed_count = len(recorder.checks) - passed_count
    report = {
        "archive_provenance": archive_report,
        "causal_recomputation": {
            "feature_names": causal_features,
            "sample_size": sample_size,
        },
        "checks": [_json_safe(asdict(check)) for check in recorder.checks],
        "dataset_version": manifest["dataset_version"],
        "file_checksums": file_checksums,
        "numeric_tolerance": NUMERIC_TOLERANCE,
        "overall_status": "pass" if failed_count == 0 else "fail",
        "structural_counts": {
            **event_counts,
            "attacker_devices_by_subtype": subtype_counts,
            "devices_by_group_and_split": split_group_counts,
            "devices_by_label": label_counts,
            "devices_by_population": population_counts,
            "devices_by_split": split_counts,
            "distinct_devices_ever_tagged_by_scenario": devices_by_scenario,
            "normal_device_scenario_membership": normal_membership,
            "sessions_by_scenario": sessions_by_scenario,
        },
        "total_checks_failed": failed_count,
        "total_checks_passed": passed_count,
    }
    logger.info(
        "Completed frozen dataset validation: %d passed, %d failed",
        passed_count,
        failed_count,
    )
    return ValidationResult(tuple(recorder.checks), report)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def serialize_report(report: dict[str, Any]) -> bytes:
    """Serialize a validation report with stable ordering and whitespace."""
    return (json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def write_validation_report(report: dict[str, Any], path: Path) -> None:
    """Atomically replace the report so stale success cannot survive a failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = serialize_report(report)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    logger.info("Wrote deterministic validation report to %s", path.name)


def require_valid_dataset(result: ValidationResult) -> None:
    """Raise the project boundary error when any required check failed."""
    if not result.passed:
        failed = [check.name for check in result.checks if not check.passed]
        raise DataValidationError(
            f"frozen dataset failed {len(failed)} required checks: {failed}"
        )
