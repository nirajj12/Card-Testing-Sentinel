"""Frozen v4 schemas and categorical contracts."""

from card_testing_sentinel.features.spec import MODEL_FEATURES

RAW_EVENT_COLUMNS = (
    "event_id",
    "event_sequence",
    "timestamp",
    "device_id",
    "session_id",
    "ip_hash",
    "event_type",
    "card_token",
    "card_bin",
    "amount",
    "declined",
    "decline_reason",
    "population",
    "attack_subtype",
    "scenario_tag",
    "entity_label",
)

ENRICHED_EVENT_COLUMNS = RAW_EVENT_COLUMNS + MODEL_FEATURES
DEVICE_SPLIT_COLUMNS = ("device_id", "group", "split")

EVENT_TYPES = frozenset({"authorization", "completion"})
POPULATIONS = frozenset({"normal", "flash_sale", "attack"})
ATTACK_SUBTYPES = frozenset({"burst", "evasive", "patient"})
SPLITS = frozenset({"train", "validation", "test"})
