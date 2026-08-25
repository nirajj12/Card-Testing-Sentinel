import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.features.batch import replay_partitioned_events
from card_testing_sentinel.v2.features.spec import MODEL_FEATURES


def _opaque(kind: str, number: int) -> str:
    return f"{kind}_{number:07d}"


def _split_devices(devices: pd.DataFrame, fraction: float, seed: int) -> pd.DataFrame:
    parts = []
    for _, group in devices.groupby("scenario_tag", sort=True):
        ranked = group.copy()
        ranked["rank"] = ranked.device_id.map(
            lambda value: hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
        )
        ranked = ranked.sort_values("rank")
        validation_count = round(len(ranked) * fraction)
        ranked["split"] = "train"
        ranked.iloc[:validation_count, ranked.columns.get_loc("split")] = "validation"
        parts.append(ranked.drop(columns="rank"))
    return pd.concat(parts).sort_values("device_id").reset_index(drop=True)


def generate_frames(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(int(config["seed"]))
    configured_start = config["start_timestamp"]
    start = (
        configured_start
        if isinstance(configured_start, datetime)
        else datetime.fromisoformat(configured_start)
    ).astimezone(UTC)
    events = []
    devices = []
    sequence = 0
    device_number = 0
    request_number = 0
    card_number = 0
    scenario_counts = config["device_counts"]

    for scenario, count in scenario_counts.items():
        for _local_index in range(int(count)):
            device_number += 1
            device_id = _opaque("dev", device_number)
            attack = scenario.startswith("attack_")
            population = (
                "attack"
                if attack
                else ("flash_sale" if scenario.startswith("flash_") else "normal")
            )
            subtype = scenario.removeprefix("attack_") if attack else None
            devices.append(
                {
                    "device_id": device_id,
                    "population": population,
                    "attack_subtype": subtype,
                    "scenario_tag": scenario,
                    "label": int(attack),
                }
            )
            if scenario == "attack_patient":
                sessions = int(rng.integers(2, 5))
            else:
                session_draw = rng.random()
                sessions = (
                    3 if session_draw < 0.03 else (2 if session_draw < 0.15 else 1)
                )
            base = start + timedelta(minutes=int(rng.integers(0, 60 * 24 * 30)))
            device_cards = []
            approved_request = None
            approved_session = None
            completed_requests = set()
            final_time = base
            session_day_offset = 0
            for session_index in range(sessions):
                session_id = f"{device_id}_s{session_index + 1}"
                if session_index:
                    session_day_offset += int(rng.integers(1, 4))
                session_start = base + timedelta(days=session_day_offset)
                if scenario == "attack_burst":
                    attempts = int(rng.integers(6, 13))
                    gap = (8, 25) if rng.random() < 0.20 else (1, 5)
                elif scenario == "attack_evasive":
                    attempts, gap = int(rng.integers(5, 10)), (20, 180)
                elif scenario == "attack_patient":
                    attempts, gap = int(rng.integers(2, 4)), (180, 1200)
                elif scenario in {"normal_bad_luck", "flash_hard_retry"}:
                    attempts = int(rng.integers(3, 5))
                    gap = (2, 10) if rng.random() < 0.15 else (20, 100)
                else:
                    attempts, gap = int(rng.integers(1, 3)), (20, 180)
                same_card_bias = 0.85 if scenario == "flash_hard_retry" else 0.55
                ip_rotation = int(rng.integers(4, 7)) if attack else attempts + 1
                session_elapsed = 0
                for attempt in range(attempts):
                    request_number += 1
                    if not device_cards or rng.random() > same_card_bias:
                        card_number += 1
                        device_cards.append(card_number)
                    card = (
                        device_cards[-1]
                        if rng.random() < same_card_bias
                        else int(rng.choice(device_cards))
                    )
                    request_id = _opaque("req", request_number)
                    session_elapsed += int(rng.integers(*gap))
                    timestamp = session_start + timedelta(seconds=session_elapsed)
                    ip_pool = 40 if population == "flash_sale" else 1200
                    ip_index = (
                        device_number // ip_rotation + attempt // ip_rotation
                    ) % ip_pool
                    amount = float(np.round(rng.lognormal(2.2, 0.65), 2))
                    if attack and rng.random() < 0.28:
                        amount = float(np.round(rng.uniform(1, 4), 2))
                    if scenario == "flash_hard_retry" and attempt:
                        amount = events[-2]["amount"] if rng.random() < 0.8 else amount
                    campaign = population == "flash_sale" or rng.random() < 0.12
                    card_bin = str(410000 + ((card // 3) % 20))
                    common = {
                        "request_id": request_id,
                        "device_id": device_id,
                        "session_id": session_id,
                        "population": population,
                        "attack_subtype": subtype,
                        "scenario_tag": scenario,
                        "label": int(attack),
                    }
                    sequence += 1
                    events.append(
                        {
                            "event_id": _opaque("evt", sequence),
                            "event_sequence": sequence,
                            "timestamp": timestamp.isoformat(),
                            "event_type": "authorization_request",
                            "ip_fingerprint": _opaque("ip", ip_index),
                            "card_fingerprint": _opaque("card", card),
                            "card_bin": card_bin,
                            "amount": amount,
                            "currency": config["currency"],
                            "campaign_active": campaign,
                            "authorization_result": None,
                            "decline_reason": None,
                            **common,
                        }
                    )
                    if scenario in {"normal_bad_luck", "flash_hard_retry"}:
                        approved = attempt >= 2 and rng.random() < 0.8
                    else:
                        approved = rng.random() < (0.45 if attack else 0.88)
                    outcome_time = timestamp + timedelta(
                        seconds=int(rng.integers(1, 4))
                    )
                    sequence += 1
                    events.append(
                        {
                            "event_id": _opaque("evt", sequence),
                            "event_sequence": sequence,
                            "timestamp": outcome_time.isoformat(),
                            "event_type": "authorization_outcome",
                            "ip_fingerprint": None,
                            "card_fingerprint": None,
                            "card_bin": None,
                            "amount": None,
                            "currency": None,
                            "campaign_active": None,
                            "authorization_result": "approved"
                            if approved
                            else "declined",
                            "decline_reason": None if approved else "generic_decline",
                            **common,
                        }
                    )
                    final_time = outcome_time
                    if approved:
                        approved_request = request_id
                        approved_session = session_id
                        if not attack:
                            if session_index < sessions - 1 and rng.random() < 0.82:
                                sequence += 1
                                completion_time = outcome_time + timedelta(
                                    seconds=int(rng.integers(30, 180))
                                )
                                events.append(
                                    {
                                        "event_id": _opaque("evt", sequence),
                                        "request_id": approved_request,
                                        "event_sequence": sequence,
                                        "timestamp": completion_time.isoformat(),
                                        "event_type": "checkout_completion",
                                        "device_id": device_id,
                                        "session_id": approved_session,
                                        "ip_fingerprint": None,
                                        "card_fingerprint": None,
                                        "card_bin": None,
                                        "amount": None,
                                        "currency": None,
                                        "campaign_active": None,
                                        "authorization_result": None,
                                        "decline_reason": None,
                                        "population": population,
                                        "attack_subtype": subtype,
                                        "scenario_tag": scenario,
                                        "label": int(attack),
                                    }
                                )
                                completed_requests.add(approved_request)
                                final_time = completion_time
                            break
            if (
                approved_request
                and approved_request not in completed_requests
                and rng.random() < (0.55 if attack else 0.82)
            ):
                sequence += 1
                events.append(
                    {
                        "event_id": _opaque("evt", sequence),
                        "request_id": approved_request,
                        "event_sequence": sequence,
                        "timestamp": (
                            final_time + timedelta(seconds=int(rng.integers(30, 180)))
                        ).isoformat(),
                        "event_type": "checkout_completion",
                        "device_id": device_id,
                        "session_id": approved_session,
                        "ip_fingerprint": None,
                        "card_fingerprint": None,
                        "card_bin": None,
                        "amount": None,
                        "currency": None,
                        "campaign_active": None,
                        "authorization_result": None,
                        "decline_reason": None,
                        "population": population,
                        "attack_subtype": subtype,
                        "scenario_tag": scenario,
                        "label": int(attack),
                    }
                )
    event_frame = (
        pd.DataFrame(events)
        .sort_values(["timestamp", "event_sequence"], kind="mergesort")
        .reset_index(drop=True)
    )
    device_frame = _split_devices(
        pd.DataFrame(devices), config["validation_fraction"], int(config["seed"])
    )
    return event_frame, device_frame


def write_development_bundle(config_path: Path, output_dir: Path) -> dict:
    config = yaml.safe_load(config_path.read_text())
    raw, splits = generate_frames(config)
    features = replay_partitioned_events(raw, splits)
    raw_text = raw.to_csv(index=False, lineterminator="\n", float_format="%.6f")
    feature_text = features.to_csv(
        index=False, lineterminator="\n", float_format="%.6f"
    )
    split_text = splits.to_csv(index=False, lineterminator="\n")
    files = {
        "raw_events.csv": raw_text,
        "events_with_features.csv": feature_text,
        "device_splits.csv": split_text,
    }
    hashes = {}
    for name, content in files.items():
        atomic_write_text(output_dir / name, content)
        hashes[name] = hashlib.sha256(content.encode()).hexdigest()
    manifest = {
        "version": config["version"],
        "seed": config["seed"],
        "generation_config_sha256": hashlib.sha256(
            config_path.read_bytes()
        ).hexdigest(),
        "feature_contract_sha256": hashlib.sha256(
            "\n".join(MODEL_FEATURES).encode()
        ).hexdigest(),
        "blind_test_included": False,
        "counts": {
            "devices": len(splits),
            "events": len(raw),
            "requests": int(raw.event_type.eq("authorization_request").sum()),
            "sessions": int(raw.session_id.nunique()),
            "train_devices": int(splits.split.eq("train").sum()),
            "validation_devices": int(splits.split.eq("validation").sum()),
        },
        "scenario_device_counts": splits.scenario_tag.value_counts()
        .sort_index()
        .to_dict(),
        "sha256": hashes,
    }
    atomic_write_json(output_dir / "manifest.json", manifest)
    return manifest
