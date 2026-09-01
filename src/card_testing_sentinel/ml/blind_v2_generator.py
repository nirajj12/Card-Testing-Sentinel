"""Independent raw-event generator for the unevaluated Blind v2 benchmark.

This module never imports modeling, policy, training, evaluation, or policy-search
code. Population and scenario live only in the separate label table; observable
payment behavior is determined by scenario parameters, not by a label branch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.features.specification_v2 import (
    FEATURE_CONTRACT_V2_VERSION,
    MODEL_FEATURES_V2_SHA256,
)
from card_testing_sentinel.ml.merchants import (
    MerchantProfile,
    make_merchant,
    resolve_calendar,
)
from card_testing_sentinel.ml.primitives import (
    EVENT_COLUMNS,
    Instrument,
    blank_event,
    choose_amount,
    failure_reason,
    lognormal_gap,
    new_instrument,
    resolve_attempt,
)

BLIND_VERSION = "v2"
IDENTITY_PREFIX = "bv2"
LABEL_COLUMNS = (
    "device_id",
    "actor_id",
    "merchant_id",
    "merchant_kind",
    "merchant_origin",
    "population",
    "scenario",
    "label",
    "linkage_class",
)


class BlindV2Error(RuntimeError):
    """Generation would violate the benchmark specification."""


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def required_merchant_kinds(config: dict) -> tuple[str, ...]:
    return tuple(sorted(config["merchants"]["kinds"]))


def build_merchants_v2(config: dict) -> list[MerchantProfile]:
    spec = config["merchants"]
    kinds = spec["kinds"]
    names = sorted(kinds)
    count = int(spec["count"])
    if count < len(names):
        raise BlindV2Error("every declared Blind v2 merchant kind needs an instance")
    rng = np.random.default_rng(int(spec["seed"]))
    weights = np.array([float(kinds[name]["weight"]) for name in names])
    extras = list(rng.choice(names, size=count - len(names), p=weights / weights.sum()))
    calendar = resolve_calendar(spec)
    merchants = []
    for index, kind in enumerate(names + extras):
        merchant = make_merchant(rng, index, str(kind), kinds[kind], calendar)
        merchants.append(
            replace(merchant, merchant_id=f"{IDENTITY_PREFIX}_mer_{index + 1:03d}")
        )
    return merchants


def resolved_scenarios(config: dict) -> dict[str, dict]:
    defaults = config["scenario_defaults"]
    return {
        name: {**defaults, **spec, "name": name}
        for name, spec in sorted(config["scenarios"].items())
    }


class BlindV2Generator:
    def __init__(self, config: dict) -> None:
        if str(config["blind_version"]) != BLIND_VERSION:
            raise BlindV2Error("Blind v2 generator requires blind_version: v2")
        self.config = config
        self.rng = np.random.default_rng(int(config["seed"]))
        self.scenarios = resolved_scenarios(config)
        self.merchants = build_merchants_v2(config)
        self.by_kind: dict[str, list[MerchantProfile]] = {}
        for merchant in self.merchants:
            self.by_kind.setdefault(merchant.kind, []).append(merchant)
        self.shared_ips = [
            f"{IDENTITY_PREFIX}_ip_shared_{index:04d}"
            for index in range(int(config["identity"]["shared_ip_pool"]))
        ]
        self.counters = {"actor": 0, "device": 0, "event": 0, "request": 0}

    def _next(self, kind: str) -> int:
        self.counters[kind] += 1
        return self.counters[kind]

    def _pick_merchant(self, scenario: dict) -> MerchantProfile:
        declared = scenario.get("merchant_kinds")
        pool = self.merchants
        if declared:
            pool = [
                merchant for kind in declared for merchant in self.by_kind.get(kind, [])
            ]
            if not pool:
                raise BlindV2Error(
                    f"scenario {scenario['name']} has no compatible merchant; "
                    "silent fallback is forbidden"
                )
        merchant = pool[int(self.rng.integers(0, len(pool)))]
        return merchant

    def _draw_range(self, values) -> float:
        return float(self.rng.uniform(float(values[0]), float(values[1])))

    def _draw_count(self, values) -> int:
        return int(self.rng.integers(int(values[0]), int(values[1]) + 1))

    def _actor_start(self, scenario: dict, merchant: MerchantProfile) -> datetime:
        window = self.config["window"]
        start = window["start"]
        if not isinstance(start, datetime):
            start = datetime.fromisoformat(str(start))
        days = int(window["actor_start_window_days"])
        moment = start + timedelta(seconds=float(self.rng.uniform(0, days * 86400)))
        if scenario.get("prefers_campaign"):
            end = start + timedelta(days=days)
            live = [
                (opens, closes)
                for opens, closes in merchant.campaign_windows
                if opens < end and closes > start
            ]
            if live:
                opens, closes = live[int(self.rng.integers(0, len(live)))]
                low = max(start, opens).timestamp()
                high = min(end, closes).timestamp()
                if high > low:
                    moment = datetime.fromtimestamp(
                        float(self.rng.uniform(low, high)), tz=UTC
                    )
        return moment

    def _gap(self, scenario: dict, attempt: int) -> float:
        cadence = str(scenario["cadence"])
        if cadence == "day_spread":
            seconds = self._draw_range(scenario["gap_days"]) * 86400
        elif cadence == "burst_pause":
            burst_size = self._draw_count(scenario["burst_size"])
            source = (
                scenario["pause_seconds"]
                if attempt and attempt % burst_size == 0
                else scenario["gap_seconds"]
            )
            seconds = self._draw_range(source)
        elif cadence == "variable":
            low, high = map(float, scenario["gap_seconds"])
            seconds = float(np.exp(self.rng.uniform(np.log(max(low, 1)), np.log(high))))
        else:
            seconds = lognormal_gap(
                self.rng,
                self._draw_range(scenario["gap_seconds"]),
                self._draw_range(scenario["gap_spread"]),
            )
        if self.rng.random() < float(scenario.get("large_gap_probability", 0.0)):
            seconds += self._draw_range(scenario["large_gap_days"]) * 86400
        return max(seconds, 1.0)

    def _customer_for(
        self,
        actor_number: int,
        device_number: int,
        presence: float,
        linkage: str,
    ) -> str | None:
        if self.rng.random() >= presence:
            return None
        primary = f"{IDENTITY_PREFIX}_cus_{actor_number:06d}"
        local = f"{primary}_d{device_number}"
        if linkage == "strong":
            return primary
        if linkage == "partial":
            return primary if self.rng.random() < 0.68 else local
        return primary if self.rng.random() < 0.20 else local

    def _append_attempt(
        self,
        events: list[dict],
        *,
        clock: datetime,
        merchant: MerchantProfile,
        customer: str | None,
        device: str,
        session: str,
        ip: str,
        instrument: Instrument,
        method_validity: float,
        network_instability: float,
        checkout_completion: float,
        amount_weights: dict,
        previous_amount: float | None,
    ) -> tuple[datetime, Instrument, float]:
        amount = choose_amount(self.rng, merchant, amount_weights, previous_amount)
        request_id = f"{IDENTITY_PREFIX}_req_{self._next('request'):08d}"
        events.append(
            blank_event(
                "authorization_request",
                clock,
                f"{IDENTITY_PREFIX}_evt_{self._next('event'):09d}",
                request_id=request_id,
                merchant_id=merchant.merchant_id,
                customer_id=customer,
                device_id=device,
                session_id=session,
                ip_fingerprint=ip,
                amount=amount,
                currency=self.config["currency"],
                campaign_active=merchant.in_campaign(clock),
            )
        )
        approved, cause = resolve_attempt(
            self.rng, merchant, instrument, network_instability
        )
        if cause == "instrument":
            instrument.declined_before = True
        outcome_time = clock + timedelta(
            seconds=self._draw_range(self.config["identity"]["outcome_lag_seconds"])
        )
        events.append(
            blank_event(
                "authorization_outcome",
                outcome_time,
                f"{IDENTITY_PREFIX}_evt_{self._next('event'):09d}",
                request_id=request_id,
                device_id=device,
                session_id=session,
                authorization_result="approved" if approved else "declined",
                failure_reason=None
                if approved
                else failure_reason(self.rng, instrument, cause),
                payment_method=instrument.method,
                card_last4=instrument.last4 if instrument.method == "card" else None,
                card_network=instrument.network
                if instrument.method == "card"
                else None,
                card_type=instrument.card_type if instrument.method == "card" else None,
                card_issuer=instrument.issuer if instrument.method == "card" else None,
                international=instrument.international,
            )
        )
        finished = outcome_time
        if approved and self.rng.random() < checkout_completion:
            finished += timedelta(
                seconds=self._draw_range(
                    self.config["identity"]["checkout_lag_seconds"]
                )
            )
            events.append(
                blank_event(
                    "checkout_completion",
                    finished,
                    f"{IDENTITY_PREFIX}_evt_{self._next('event'):09d}",
                    request_id=request_id,
                    device_id=device,
                    session_id=session,
                )
            )
        return finished, instrument, amount

    def _generate_actor(self, scenario: dict) -> tuple[list[dict], list[dict]]:
        actor_number = self._next("actor")
        actor_id = f"{IDENTITY_PREFIX}_act_{actor_number:06d}"
        merchant = self._pick_merchant(scenario)
        attempts = self._draw_count(scenario["attempts"])
        device_count = min(self._draw_count(scenario["devices"]), attempts)
        devices = [
            f"{IDENTITY_PREFIX}_dev_{self._next('device'):07d}"
            for _ in range(device_count)
        ]
        device_numbers = {device: index for index, device in enumerate(devices)}
        sessions = {device: 0 for device in devices}
        private_ips = {
            device: [
                f"{IDENTITY_PREFIX}_ip_{actor_number:06d}_{index}_{slot}"
                for slot in range(3)
            ]
            for index, device in enumerate(devices)
        }
        shared_probability = self._draw_range(scenario["shared_ip_probability"])
        use_shared = self.rng.random() < shared_probability
        current_ips = {
            device: (
                self.shared_ips[int(self.rng.integers(0, len(self.shared_ips)))]
                if use_shared
                else private_ips[device][0]
            )
            for device in devices
        }
        presence = self._draw_range(scenario["customer_presence"])
        linkage = str(scenario["linkage_class"])
        method_validity = self._draw_range(scenario["method_validity"])
        network_instability = self._draw_range(scenario["network_instability"])
        checkout_completion = self._draw_range(scenario["checkout_completion"])
        session_rotation = self._draw_range(scenario["session_rotation"])
        ip_rotation = self._draw_range(scenario["ip_rotation"])
        instrument_reuse = self._draw_range(scenario["instrument_reuse"])
        clock = self._actor_start(scenario, merchant)
        instrument = new_instrument(
            self.rng, self.config["instruments"], max(0.90, method_validity)
        )
        previous_amount: float | None = None
        events: list[dict] = []

        warmups = self._draw_count(scenario["warmup_attempts"])
        for index in range(warmups):
            device = devices[index % len(devices)]
            if index:
                clock += timedelta(days=self._draw_range(scenario["warmup_gap_days"]))
            session = (
                f"{IDENTITY_PREFIX}_ses_{actor_number:06d}_"
                f"{device_numbers[device]}_w{index}"
            )
            customer = self._customer_for(
                actor_number, device_numbers[device], max(presence, 0.72), linkage
            )
            clock, instrument, previous_amount = self._append_attempt(
                events,
                clock=clock,
                merchant=merchant,
                customer=customer,
                device=device,
                session=session,
                ip=current_ips[device],
                instrument=instrument,
                method_validity=0.96,
                network_instability=0.02,
                checkout_completion=0.96,
                amount_weights={
                    "merchant_typical": 0.82,
                    "repeat": 0.12,
                    "varied": 0.06,
                },
                previous_amount=previous_amount,
            )
        if warmups:
            clock += timedelta(
                days=self._draw_range(scenario["warmup_to_main_gap_days"])
            )
        instrument = new_instrument(
            self.rng, self.config["instruments"], method_validity
        )

        for attempt in range(attempts):
            device = devices[attempt % len(devices)]
            device_number = device_numbers[device]
            if attempt:
                clock += timedelta(seconds=self._gap(scenario, attempt))
            if self.rng.random() < session_rotation:
                sessions[device] += 1
            if self.rng.random() < ip_rotation:
                current_ips[device] = (
                    self.shared_ips[int(self.rng.integers(0, len(self.shared_ips)))]
                    if use_shared and self.rng.random() < 0.72
                    else private_ips[device][int(self.rng.integers(0, 3))]
                )
            if self.rng.random() >= instrument_reuse:
                instrument = new_instrument(
                    self.rng, self.config["instruments"], method_validity
                )
            customer = self._customer_for(
                actor_number, device_number, presence, linkage
            )
            session = (
                f"{IDENTITY_PREFIX}_ses_{actor_number:06d}_{device_number}_"
                f"{sessions[device]}"
            )
            clock, instrument, previous_amount = self._append_attempt(
                events,
                clock=clock,
                merchant=merchant,
                customer=customer,
                device=device,
                session=session,
                ip=current_ips[device],
                instrument=instrument,
                method_validity=method_validity,
                network_instability=network_instability,
                checkout_completion=checkout_completion,
                amount_weights=scenario["amount_style_weights"],
                previous_amount=previous_amount,
            )

        labels = [
            {
                "device_id": device,
                "actor_id": actor_id,
                "merchant_id": merchant.merchant_id,
                "merchant_kind": merchant.kind,
                "merchant_origin": merchant.origin,
                "population": scenario["population"],
                "scenario": scenario["name"],
                "label": int(scenario["population"] == "attack"),
                "linkage_class": linkage,
            }
            for device in devices
        ]
        return events, labels

    def generate(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        target = int(self.config["population"]["target_devices"])
        attack_target = int(
            round(
                target
                * float(self.config["population"]["benchmark_attack_device_fraction"])
            )
        )
        targets = {"attack": attack_target, "legitimate": target - attack_target}
        minimum = int(self.config["population"]["minimum_actors_per_scenario"])
        events: list[dict] = []
        labels: list[dict] = []
        counts = {"attack": 0, "legitimate": 0}

        for scenario in self.scenarios.values():
            for _ in range(minimum):
                actor_events, actor_labels = self._generate_actor(scenario)
                events.extend(actor_events)
                labels.extend(actor_labels)
                counts[str(scenario["population"])] += len(actor_labels)

        by_population = {
            population: [
                scenario
                for scenario in self.scenarios.values()
                if scenario["population"] == population
            ]
            for population in ("attack", "legitimate")
        }
        for population in ("legitimate", "attack"):
            pool = by_population[population]
            weights = np.array([float(scenario["weight"]) for scenario in pool])
            while counts[population] < targets[population]:
                scenario = pool[
                    int(self.rng.choice(len(pool), p=weights / weights.sum()))
                ]
                actor_events, actor_labels = self._generate_actor(scenario)
                events.extend(actor_events)
                labels.extend(actor_labels)
                counts[population] += len(actor_labels)

        raw = pd.DataFrame(events, columns=list(EVENT_COLUMNS))
        raw = raw.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        raw["event_sequence"] = range(1, len(raw) + 1)
        raw["timestamp"] = raw.timestamp.map(lambda value: value.isoformat())
        label_frame = pd.DataFrame(labels, columns=list(LABEL_COLUMNS))
        return raw, label_frame


def assert_after_dataset_v3(raw: pd.DataFrame, dataset_manifest: Path, floor) -> dict:
    first = pd.to_datetime(raw.timestamp, format="ISO8601").min().to_pydatetime()
    if not isinstance(floor, datetime):
        floor = datetime.fromisoformat(str(floor))
    manifest = json.loads(dataset_manifest.read_text())
    last = max(
        datetime.fromisoformat(split["last_event"])
        for split in manifest["splits"].values()
    )
    if first < floor or first <= last:
        raise BlindV2Error(
            f"Blind v2 starts at {first}; Dataset v3 ends at {last} "
            f"and floor is {floor}"
        )
    return {
        "dataset_v3_last_event": last.isoformat(),
        "blind_v2_first_event": first.isoformat(),
        "separation_days": round((first - last).total_seconds() / 86400, 3),
    }


def build_manifest(
    config: dict,
    raw: pd.DataFrame,
    labels: pd.DataFrame,
    config_path: Path,
    spec_path: Path,
    separation: dict,
) -> dict:
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    devices = labels.drop_duplicates("device_id")
    request_labels = requests.merge(
        devices[["device_id", "label", "scenario"]], on="device_id", how="left"
    )
    presence = requests.customer_id.notna()
    times = pd.to_datetime(raw.timestamp, format="ISO8601")
    return {
        "blind_version": BLIND_VERSION,
        "dataset_name": config["dataset_name"],
        "generator_version": config["generator_version"],
        "seed": int(config["seed"]),
        "merchant_seed": int(config["merchants"]["seed"]),
        "blind_v2_config_sha256": sha256_file(config_path),
        "blind_v2_spec_sha256": sha256_file(spec_path),
        "feature_contract_version": FEATURE_CONTRACT_V2_VERSION,
        "feature_contract_sha256": MODEL_FEATURES_V2_SHA256,
        "events": int(len(raw)),
        "requests": int(len(requests)),
        "outcomes": int(raw.event_type.eq("authorization_outcome").sum()),
        "checkouts": int(raw.event_type.eq("checkout_completion").sum()),
        "devices": int(devices.device_id.nunique()),
        "actors": int(labels.actor_id.nunique()),
        "customers_observed": int(requests.customer_id.nunique()),
        "merchants": int(labels.merchant_id.nunique()),
        "attack_devices": int(devices.label.eq(1).sum()),
        "legitimate_devices": int(devices.label.eq(0).sum()),
        "realized_attack_device_fraction": round(float(devices.label.mean()), 4),
        "realized_attack_request_fraction": round(
            float(request_labels.label.mean()), 4
        ),
        "customer_id_presence": {
            "overall_request_share": round(float(presence.mean()), 4),
            "attack_request_share": round(
                float(
                    request_labels.loc[request_labels.label.eq(1), "customer_id"]
                    .notna()
                    .mean()
                ),
                4,
            ),
            "legitimate_request_share": round(
                float(
                    request_labels.loc[request_labels.label.eq(0), "customer_id"]
                    .notna()
                    .mean()
                ),
                4,
            ),
        },
        "configured_scenarios": sorted(config["scenarios"]),
        "scenario_devices": {
            str(key): int(value)
            for key, value in devices.groupby("scenario").device_id.nunique().items()
        },
        "scenario_requests": {
            str(key): int(value)
            for key, value in request_labels.groupby("scenario").size().items()
        },
        "configured_merchant_kinds": list(required_merchant_kinds(config)),
        "realized_merchant_kinds": sorted(devices.merchant_kind.unique()),
        "merchant_instances_per_kind": {
            str(key): int(value)
            for key, value in labels.drop_duplicates("merchant_id")
            .groupby("merchant_kind")
            .size()
            .items()
        },
        "merchant_kind_devices": {
            str(key): int(value)
            for key, value in devices.groupby("merchant_kind")
            .device_id.nunique()
            .items()
        },
        "linkage_class_devices": {
            str(key): int(value)
            for key, value in devices.groupby("linkage_class")
            .device_id.nunique()
            .items()
        },
        "window": {
            "configured_start": str(config["window"]["start"]),
            "first_event": times.min().isoformat(),
            "last_event": times.max().isoformat(),
            "realized_span_days": round(
                float((times.max() - times.min()).total_seconds() / 86400), 3
            ),
        },
        "temporal_separation": separation,
        "environment": {
            "generator": "numpy.random.Generator(PCG64)",
            "serialization": "UTF-8, LF, pandas CSV",
        },
        "prevalence_disclosure": (
            "Attack devices are deliberately enriched for per-family diagnostics; "
            "this is not an estimate of card-testing prevalence."
        ),
        "contains_model_scores": False,
        "contains_policy_decisions": False,
        "evaluated": False,
        "consumed": False,
    }


def generate_blind_v2_bundle(
    config: dict, config_path: Path, spec_path: Path, dataset_manifest: Path
) -> dict:
    generator = BlindV2Generator(config)
    raw, labels = generator.generate()
    separation = assert_after_dataset_v3(
        raw, dataset_manifest, config["window"]["must_start_after"]
    )
    return {
        "raw_events": raw,
        "labels": labels,
        "manifest": build_manifest(
            config, raw, labels, config_path, spec_path, separation
        ),
    }
