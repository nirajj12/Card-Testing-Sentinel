from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.v2.data.generator import write_development_bundle
from card_testing_sentinel.v2.data.validation import validate_bundle
from card_testing_sentinel.v2.features.batch import replay_events


def test_batch_replay_is_deterministic_and_one_row_per_request(tmp_path):
    config = yaml.safe_load(Path("configs/v2/generation.yaml").read_text())
    config["device_counts"] = {name: 2 for name in config["device_counts"]}
    config_path = tmp_path / "generation.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=True))
    first, second = tmp_path / "first", tmp_path / "second"
    manifest_one = write_development_bundle(config_path, first)
    manifest_two = write_development_bundle(config_path, second)
    assert manifest_one["sha256"] == manifest_two["sha256"]
    for name in manifest_one["sha256"]:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    raw = pd.read_csv(first / "raw_events.csv")
    rebuilt = replay_events(raw)
    assert len(rebuilt) == raw.event_type.eq("authorization_request").sum()
    assert not {"card_token", "raw_ip", "pan", "cvv", "expiry"} & set(raw.columns)


def test_checked_in_development_bundle_passes_full_validation():
    report = validate_bundle(Path.cwd())
    assert report["status"] == "passed"
    assert report["checks"]["online_batch_parity"]["passed"] is True
    assert report["checks"]["device_split_overlap"]["detail"] == 0
