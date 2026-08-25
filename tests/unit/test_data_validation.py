from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.common.exceptions import DataValidationError
from card_testing_sentinel.data.contracts import RAW_EVENT_COLUMNS
from card_testing_sentinel.data.validation import (
    ValidationCheck,
    ValidationResult,
    check_exact_columns,
    normal_scenario_membership,
    require_valid_dataset,
    scenario_counts,
    serialize_report,
    validate_entity_contracts,
    validate_event_identity,
    validate_event_semantics,
    validate_feature_domains,
    validate_split_integrity,
    write_validation_report,
)
from card_testing_sentinel.features.spec import MODEL_FEATURES


def _events() -> pd.DataFrame:
    rows = [
        {
            "event_id": "event_1",
            "event_sequence": 1,
            "timestamp": pd.Timestamp("2026-08-01T00:00:00"),
            "device_id": "device_1",
            "session_id": "session_1",
            "ip_hash": "ip_1",
            "event_type": "authorization",
            "card_token": "token_1",
            "card_bin": "111111",
            "amount": 5.0,
            "declined": True,
            "decline_reason": "do_not_honor",
            "population": "normal",
            "attack_subtype": pd.NA,
            "scenario_tag": "normal_standard",
            "entity_label": 0,
        },
        {
            "event_id": "event_2",
            "event_sequence": 2,
            "timestamp": pd.Timestamp("2026-08-01T00:00:05"),
            "device_id": "device_1",
            "session_id": "session_1",
            "ip_hash": "ip_1",
            "event_type": "authorization",
            "card_token": "token_1",
            "card_bin": "111111",
            "amount": 5.0,
            "declined": False,
            "decline_reason": pd.NA,
            "population": "normal",
            "attack_subtype": pd.NA,
            "scenario_tag": "normal_standard",
            "entity_label": 0,
        },
        {
            "event_id": "event_3",
            "event_sequence": 3,
            "timestamp": pd.Timestamp("2026-08-01T00:00:06"),
            "device_id": "device_1",
            "session_id": "session_1",
            "ip_hash": "ip_1",
            "event_type": "completion",
            "card_token": pd.NA,
            "card_bin": pd.NA,
            "amount": np.nan,
            "declined": pd.NA,
            "decline_reason": pd.NA,
            "population": "normal",
            "attack_subtype": pd.NA,
            "scenario_tag": "normal_standard",
            "entity_label": 0,
        },
        {
            "event_id": "event_4",
            "event_sequence": 4,
            "timestamp": pd.Timestamp("2026-08-02T00:00:00"),
            "device_id": "device_1",
            "session_id": "session_2",
            "ip_hash": "ip_2",
            "event_type": "authorization",
            "card_token": "token_2",
            "card_bin": "222222",
            "amount": 10.0,
            "declined": False,
            "decline_reason": pd.NA,
            "population": "normal",
            "attack_subtype": pd.NA,
            "scenario_tag": "normal_bad_luck",
            "entity_label": 0,
        },
    ]
    return pd.DataFrame(rows, columns=RAW_EVENT_COLUMNS)


def _feature_frame() -> pd.DataFrame:
    frame = pd.DataFrame({feature: [0.0, 0.0] for feature in MODEL_FEATURES})
    for feature in (
        "attempts_trailing_10s",
        "attempts_trailing_60s",
        "attempts_trailing_5min",
        "unique_cards_trailing_60s",
        "unique_cards_trailing_5min",
        "unique_bins_trailing_60s",
        "unique_bins_trailing_5min",
        "cards_this_session",
        "attempts_this_session",
        "ip_session_count_trailing_5min",
        "ip_device_count_trailing_5min",
    ):
        frame[feature] = 1.0
    frame["decline_ratio_so_far"] = 0.5
    frame["approval_ratio_so_far"] = 0.5
    frame["unique_amount_ratio"] = 1.0
    frame["card_switch_rate"] = 1.0
    return frame


def _check(checks: list[ValidationCheck], name: str) -> ValidationCheck:
    return next(check for check in checks if check.name == name)


def _split_raw() -> pd.DataFrame:
    rows = []
    for sequence, device in enumerate(("device_1", "device_2", "device_3"), 1):
        row = _events().iloc[0].copy()
        row["event_id"] = f"event_{sequence}"
        row["event_sequence"] = sequence
        row["device_id"] = device
        row["session_id"] = f"session_{sequence}"
        rows.append(row)
    return pd.DataFrame(rows, columns=RAW_EVENT_COLUMNS)


def _splits() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "device_id": ["device_1", "device_2", "device_3"],
            "group": ["normal", "normal", "normal"],
            "split": ["train", "validation", "test"],
        }
    )


def test_exact_schema_rejects_missing_and_unexpected_columns() -> None:
    actual = (*RAW_EVENT_COLUMNS[:-1], "unexpected")

    check = check_exact_columns(actual, RAW_EVENT_COLUMNS, "raw_events")

    assert not check.passed
    assert "entity_label" in check.message
    assert "unexpected" in check.message


def test_duplicate_event_ids_are_rejected() -> None:
    raw = _events()
    raw.loc[1, "event_id"] = raw.loc[0, "event_id"]

    checks = validate_event_identity(raw, _events())

    assert not _check(checks, "identity.raw_event_ids_unique").passed


def test_invalid_event_type_is_rejected() -> None:
    frame = _events()
    frame.loc[0, "event_type"] = "unknown"

    assert not _check(
        validate_event_semantics(frame), "semantics.allowed_event_types"
    ).passed


def test_missing_authorization_field_is_rejected() -> None:
    frame = _events()
    frame.loc[0, "amount"] = pd.NA

    assert not _check(
        validate_event_semantics(frame), "semantics.authorization_fields_present"
    ).passed


def test_nonnull_completion_payment_field_is_rejected() -> None:
    frame = _events()
    frame.loc[frame["event_type"].eq("completion"), "card_token"] = "token_1"

    assert not _check(
        validate_event_semantics(frame), "semantics.completion_payment_fields_null"
    ).passed


def test_label_population_mismatch_is_rejected() -> None:
    frame = _events()
    frame.loc[0, "entity_label"] = 1

    checks = validate_entity_contracts(frame)

    assert not _check(checks, "entity.label_matches_population").passed


def test_unstable_card_token_bin_mapping_is_rejected() -> None:
    frame = _events()
    frame.loc[1, "card_bin"] = "999999"

    checks = validate_entity_contracts(frame)

    assert not _check(checks, "entity.card_token_maps_to_one_bin").passed


def test_returning_device_may_change_scenario_between_sessions() -> None:
    checks = validate_entity_contracts(_events())

    assert _check(checks, "entity.session_stable_scenario_tag").passed
    assert _check(checks, "entity.device_stable_population").passed


def test_scenario_change_within_session_is_rejected() -> None:
    frame = _events()
    frame.loc[1, "scenario_tag"] = "normal_bad_luck"

    checks = validate_entity_contracts(frame)

    assert not _check(checks, "entity.session_stable_scenario_tag").passed


def test_overlapping_scenario_membership_does_not_use_first_or_last_event() -> None:
    sessions, distinct_devices = scenario_counts(_events())
    membership = normal_scenario_membership(_events())

    assert sessions["normal_standard"] == 1
    assert sessions["normal_bad_luck"] == 1
    assert distinct_devices["normal_standard"] == 1
    assert distinct_devices["normal_bad_luck"] == 1
    assert membership["both"] == 1
    assert membership["standard_only"] == 0
    assert membership["bad_luck_only"] == 0


def test_nonfinite_ratio_and_invalid_count_relationships_are_rejected() -> None:
    frame = _feature_frame()
    frame.loc[0, "mean_interarrival_s"] = np.inf
    frame.loc[0, "decline_ratio_so_far"] = 1.2
    frame.loc[0, "unique_cards_trailing_60s"] = 2

    checks = validate_feature_domains(frame)

    assert not _check(checks, "features.all_finite_and_present").passed
    assert not _check(checks, "features.ratios_in_unit_interval").passed
    assert not _check(checks, "features.unique_cards_60s_within_attempts").passed


def test_split_duplicate_and_overlap_are_rejected() -> None:
    splits = pd.concat(
        [
            _splits(),
            pd.DataFrame(
                {"device_id": ["device_1"], "group": ["normal"], "split": ["test"]}
            ),
        ],
        ignore_index=True,
    )

    checks = validate_split_integrity(_split_raw(), splits)

    assert not _check(checks, "splits.one_row_per_device").passed
    assert not _check(checks, "splits.pairwise_disjoint").passed


def test_split_missing_and_extra_devices_are_rejected() -> None:
    missing = _splits().iloc[:2].copy()
    extra = pd.concat(
        [
            _splits(),
            pd.DataFrame(
                {"device_id": ["device_4"], "group": ["normal"], "split": ["test"]}
            ),
        ],
        ignore_index=True,
    )

    missing_checks = validate_split_integrity(_split_raw(), missing)
    extra_checks = validate_split_integrity(_split_raw(), extra)

    assert not _check(missing_checks, "splits.complete_device_membership").passed
    assert not _check(extra_checks, "splits.complete_device_membership").passed


def test_required_failure_raises_data_validation_error() -> None:
    failed = ValidationCheck("example", False, "failed")
    result = ValidationResult((failed,), {"overall_status": "fail"})

    with pytest.raises(DataValidationError, match="example"):
        require_valid_dataset(result)


def test_report_serialization_and_atomic_write_are_deterministic(
    tmp_path: Path,
) -> None:
    report = {"status": "pass", "counts": {"devices": np.int64(3)}}
    path = tmp_path / "reports" / "validation.json"

    first = serialize_report(report)
    write_validation_report(report, path)
    second = path.read_bytes()
    write_validation_report(report, path)

    assert first == second == path.read_bytes()
