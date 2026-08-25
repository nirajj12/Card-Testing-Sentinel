from pathlib import Path

import pytest

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.data.validation import (
    CAUSAL_FEATURES,
    inspect_frozen_dataset,
    serialize_report,
    sha256_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_complete_frozen_v4_contract_is_valid_and_read_only() -> None:
    settings = load_config(PROJECT_ROOT / "configs" / "base.yaml")
    frozen = settings.paths.frozen_data
    filenames = (
        settings.frozen_dataset.raw_events_filename,
        settings.frozen_dataset.enriched_events_filename,
        settings.frozen_dataset.device_splits_filename,
    )
    before = {name: sha256_file(frozen / name) for name in filenames}

    first = inspect_frozen_dataset(settings)
    second = inspect_frozen_dataset(settings)

    after = {name: sha256_file(frozen / name) for name in filenames}
    assert first.passed
    assert first.report["overall_status"] == "pass"
    assert first.report["total_checks_failed"] == 0
    assert first.report["structural_counts"]["event_rows"] == 14_110
    assert first.report["structural_counts"]["authorization_rows"] == 10_603
    assert first.report["structural_counts"]["completion_rows"] == 3_507
    assert first.report["structural_counts"]["devices"] == 4_250
    assert first.report["structural_counts"]["sessions"] == 4_625
    assert first.report["causal_recomputation"]["sample_size"] == 10
    assert (
        tuple(first.report["causal_recomputation"]["feature_names"]) == CAUSAL_FEATURES
    )
    assert serialize_report(first.report) == serialize_report(second.report)
    assert before == after
