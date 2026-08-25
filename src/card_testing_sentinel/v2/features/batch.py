import pandas as pd

from card_testing_sentinel.v2.data.contracts import LifecycleEvent
from card_testing_sentinel.v2.features.engine import CausalFeatureEngine
from card_testing_sentinel.v2.features.spec import MODEL_FEATURES


def replay_events(events: pd.DataFrame) -> pd.DataFrame:
    engine = CausalFeatureEngine()
    rows = []
    ordered = events.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    contract_columns = set(LifecycleEvent.model_fields)
    for record in ordered.to_dict("records"):
        payload = {
            key: value for key, value in record.items() if key in contract_columns
        }
        payload = {key: value for key, value in payload.items() if pd.notna(value)}
        if "card_bin" in payload:
            payload["card_bin"] = str(payload["card_bin"]).removesuffix(".0")
        event = LifecycleEvent.model_validate(payload)
        if event.event_type == "authorization_request":
            snapshot = engine.precheck(event)
            rows.append(
                {
                    "event_id": event.event_id,
                    "request_id": event.request_id,
                    "timestamp": event.timestamp.isoformat(),
                    "device_id": event.device_id,
                    "session_id": event.session_id,
                    **{name: snapshot[name] for name in MODEL_FEATURES},
                    "label": int(record["label"]),
                    "population": record["population"],
                    "attack_subtype": record.get("attack_subtype"),
                    "scenario_tag": record["scenario_tag"],
                }
            )
        elif event.event_type == "authorization_outcome":
            engine.record_outcome(event)
        else:
            engine.record_completion(event)
    return pd.DataFrame(rows)


def replay_partitioned_events(
    events: pd.DataFrame, splits: pd.DataFrame
) -> pd.DataFrame:
    """Replay each evaluation partition independently, globally within partition."""
    split_map = splits.set_index("device_id")["split"]
    tagged = events.assign(split=events.device_id.map(split_map))
    if tagged.split.isna().any():
        raise ValueError("every event device must have exactly one split")
    parts = [
        replay_events(part.drop(columns="split"))
        for _, part in tagged.groupby("split", sort=True)
    ]
    return (
        pd.concat(parts, ignore_index=True)
        .sort_values(["timestamp", "event_id"], kind="mergesort")
        .reset_index(drop=True)
    )
