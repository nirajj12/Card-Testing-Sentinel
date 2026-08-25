from datetime import UTC, datetime, timedelta

import pandas as pd

from card_testing_sentinel.v2.features.batch import (
    replay_events,
    replay_partitioned_events,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _request(event, sequence, device, second):
    return {
        "event_id": f"event_{event}",
        "request_id": f"request_{event}",
        "event_sequence": sequence,
        "timestamp": (BASE + timedelta(seconds=second)).isoformat(),
        "event_type": "authorization_request",
        "device_id": device,
        "session_id": f"session_{device}",
        "ip_fingerprint": "ip_shared",
        "card_fingerprint": f"card_{device}",
        "card_bin": "410001",
        "amount": 10.0,
        "currency": "USD",
        "campaign_active": False,
        "authorization_result": None,
        "decline_reason": None,
        "label": 0,
        "population": "normal",
        "attack_subtype": None,
        "scenario_tag": "normal_standard",
    }


def _outcome(event, sequence, device, second):
    row = _request(event, sequence, device, second)
    row.update(
        event_id=f"outcome_{event}",
        event_type="authorization_outcome",
        ip_fingerprint=None,
        card_fingerprint=None,
        card_bin=None,
        amount=None,
        currency=None,
        campaign_active=None,
        authorization_result="declined",
        decline_reason="generic_decline",
    )
    return row


def test_global_interleaving_and_partition_isolation_for_shared_ip():
    raw = pd.DataFrame(
        [
            _request("train_1", 1, "device_train", 0),
            _outcome("train_1", 3, "device_train", 1),
            _request("validation_1", 4, "device_validation", 1),
            _request("train_2", 5, "device_train", 1),
        ]
    )
    global_rows = replay_events(raw).set_index("request_id")
    assert global_rows.loc["request_validation_1", "devices_per_ip_5m"] == 2
    assert global_rows.loc["request_validation_1", "requests_per_ip_5m"] == 2
    assert global_rows.loc["request_train_2", "requests_per_ip_5m"] == 3

    splits = pd.DataFrame(
        {
            "device_id": ["device_train", "device_validation"],
            "split": ["train", "validation"],
        }
    )
    isolated = replay_partitioned_events(raw, splits).set_index("request_id")
    assert isolated.loc["request_validation_1", "devices_per_ip_5m"] == 1
    assert isolated.loc["request_validation_1", "requests_per_ip_5m"] == 1
    assert isolated.loc["request_train_2", "devices_per_ip_5m"] == 1
    assert isolated.loc["request_train_2", "requests_per_ip_5m"] == 2
