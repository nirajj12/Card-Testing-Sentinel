import json
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.policy.selection import select_policies


def test_complete_v1_policy_search_matches_frozen_characterization():
    root = Path(__file__).resolve().parents[2]
    predictions = pd.read_csv(root / "artifacts/predictions/validation_predictions.csv")
    cards = pd.read_csv(
        root / "data/frozen/events_with_features.csv",
        usecols=["event_id", "card_token"],
    )
    events = predictions.merge(cards, on="event_id", how="left", validate="one_to_one")
    events["timestamp"] = pd.to_datetime(events["timestamp"])
    events["risk_score"] = events["champion_probability"]
    config = yaml.safe_load((root / "configs/policy.yaml").read_text())
    observed = select_policies(events, config)
    frozen = json.loads(
        (root / "artifacts/metrics/validation_sequential_metrics.json").read_text()
    )

    assert observed["candidate_counts"] == frozen["candidate_counts"]
    assert observed["candidate_counts"]["rules_only"] == {
        "evaluated": 15,
        "feasible": 9,
    }
    assert observed["champion"] == frozen["champion"] == "rules_only"
    for method, result in observed["methods"].items():
        assert result is not None
        assert result["feasible"] is True
        assert result["thresholds"] == frozen["methods"][method]["thresholds"]
