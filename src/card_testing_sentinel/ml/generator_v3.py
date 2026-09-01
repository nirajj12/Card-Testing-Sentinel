"""Dataset v3 generator -- the final development dataset.

Three nested entities replace Dataset V2's single flat actor:

* a **customer** joins the window once and persists (``population_v3``);
* an **actor** is a behavioural role bound to one customer;
* an **episode** is one visit -- attempts at one merchant at one time.

An actor emits several episodes days or weeks apart, so tenure, long-horizon
counts and cross-device linkage EMERGE from generated events. Nothing is
written as an attribute a feature could read directly, and no branch anywhere
keys on the label.

This module is new. It imports the neutral mechanics from ``ml/primitives.py``
and ``ml/merchants.py`` read-only and never edits them, because those files
are hashed inside the Blind v1.1 freeze bundle.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.features.specification import MODEL_FEATURES_SHA256
from card_testing_sentinel.ml.merchants import MerchantProfile
from card_testing_sentinel.ml.population_v3 import (
    CustomerProfile,
    DatasetV3Error,
    build_covering_merchants,
    build_customers,
    login_affinity,
)
from card_testing_sentinel.ml.primitives import (
    EVENT_COLUMNS,
    blank_event,
    choose_amount,
    failure_reason,
    lognormal_gap,
    new_instrument,
    resolve_attempt,
)
from card_testing_sentinel.ml.scenarios_v3 import (
    ScenarioV3,
    draw_behavior_v3,
    load_scenarios_v3,
)

SPEC_VERSION = "v3"

LABEL_COLUMNS = (
    "device_id",
    "actor_id",
    "customer_id",
    "merchant_id",
    "merchant_kind",
    "population",
    "scenario",
    "label",
    "split",
)

#: Chance an unconstrained actor shops at a different merchant on a later
#: visit, so a persistent customer's history genuinely spans businesses.
MERCHANT_REDRAW = 0.30
#: Chance a `sticky` actor uses a different one of its own devices next visit,
#: once every device has already been seen at least once.
STICKY_SWITCH = 0.35


class GeneratorV3:
    """One split of Dataset v3."""

    def __init__(
        self,
        config: dict,
        split_name: str,
        split_config: dict,
        merchants: list[MerchantProfile],
        window_start: datetime,
    ) -> None:
        self.config = config
        self.split_name = split_name
        self.split = split_config
        self.prefix = f"{split_name[0]}3_"
        self.rng = np.random.default_rng(int(split_config["seed"]))
        self.scenarios = load_scenarios_v3(config)
        self.merchants = merchants
        self.by_kind: dict[str, list[MerchantProfile]] = {}
        for merchant in merchants:
            self.by_kind.setdefault(merchant.kind, []).append(merchant)

        self.window_start = window_start
        self.window_days = int(split_config["days"])
        shift = split_config.get("shift") or {}
        self.gap_multiplier = float(shift.get("gap_multiplier", 1.0))
        self.amount_multiplier = float(shift.get("amount_multiplier", 1.0))
        self.attempts_bonus = int(shift.get("attempts_bonus", 0))

        # A customer pool large enough that no actor ever runs out; drawn
        # without replacement so a customer is never both populations.
        target_devices = int(split_config["devices"])
        self.customers = build_customers(
            np.random.default_rng(int(split_config["seed"]) + 17),
            config,
            count=target_devices + 2000,
            window_start=window_start,
            window_days=self.window_days,
            prefix=self.prefix,
        )
        self._customer_cursor = 0

        identity = config["identity"]
        self.shared_ips = [
            f"{self.prefix}ip_shared_{index:04d}"
            for index in range(int(identity["shared_ip_pool"]))
        ]
        self.mobile_ips = [
            f"{self.prefix}ip_mobile_{index:05d}"
            for index in range(int(identity["mobile_ip_pool"]))
        ]
        self.identity = identity
        self.instrument_config = config["instruments"]
        self._counters = {"event": 0, "request": 0, "actor": 0, "device": 0}

    # -- helpers -----------------------------------------------------------

    def _next(self, kind: str) -> int:
        self._counters[kind] += 1
        return self._counters[kind]

    def _take_customers(self, count: int) -> list[CustomerProfile]:
        if self._customer_cursor + count > len(self.customers):
            raise DatasetV3Error(
                f"{self.split_name}: customer pool exhausted; raise the pool size"
            )
        taken = self.customers[self._customer_cursor : self._customer_cursor + count]
        self._customer_cursor += count
        return list(taken)

    def _pick_merchant(self, scenario: ScenarioV3) -> MerchantProfile:
        """A scenario that declares merchant kinds only ever appears on them.

        Never fall back to the whole pool: a silent fallback is what broke
        the campaign families in Blind v1.0.
        """
        if not scenario.merchant_kinds:
            return self.merchants[int(self.rng.integers(0, len(self.merchants)))]
        pool = [
            merchant
            for kind in scenario.merchant_kinds
            for merchant in self.by_kind.get(kind, [])
        ]
        if not pool:
            raise DatasetV3Error(
                f"scenario '{scenario.name}' declares merchant kinds "
                f"{list(scenario.merchant_kinds)} but none was realized"
            )
        return pool[int(self.rng.integers(0, len(pool)))]

    def _draw_ip(self, customer: CustomerProfile, pool: str) -> str:
        if pool == "mobile":
            return self.mobile_ips[int(self.rng.integers(0, len(self.mobile_ips)))]
        if pool == "shared" or customer.on_shared_ip:
            return self.shared_ips[int(self.rng.integers(0, len(self.shared_ips)))]
        return customer.home_ips[int(self.rng.integers(0, len(customer.home_ips)))]

    def _episode_start(
        self, scenario: ScenarioV3, merchant: MerchantProfile, earliest: datetime
    ) -> datetime:
        """Place an episode, preferring a live campaign when the family does."""
        window_end = self.window_start + timedelta(days=self.window_days)
        if not scenario.prefers_campaign:
            return earliest
        live = [
            (opens, closes)
            for opens, closes in merchant.campaign_windows
            if closes > earliest and opens < window_end
        ]
        if not live:
            return earliest
        opens, closes = live[int(self.rng.integers(0, len(live)))]
        low = max(opens, earliest).timestamp()
        high = min(closes, window_end).timestamp()
        if high <= low:
            return earliest
        return datetime.fromtimestamp(float(self.rng.uniform(low, high)), tz=UTC)

    # -- one actor ---------------------------------------------------------

    def _generate_actor(self, scenario: ScenarioV3) -> tuple[list[dict], list[dict]]:
        behavior = draw_behavior_v3(
            self.rng,
            scenario,
            gap_multiplier=self.gap_multiplier,
            attempts_bonus=self.attempts_bonus,
        )
        actor_id = f"{self.prefix}act_{self._next('actor'):06d}"
        customers = self._take_customers(behavior.customers_on_device)
        primary = customers[0]

        # Every assigned device must actually transact (v3 fix M6): a device
        # pool wider than the run cannot all be used, so bound it first.
        episodes = behavior.episodes
        if behavior.device_mode == "spread":
            device_count = min(behavior.devices, episodes * behavior.attempts)
        else:
            device_count = min(behavior.devices, episodes)
        device_count = max(device_count, 1)
        devices = [
            f"{self.prefix}dev_{self._next('device'):06d}" for _ in range(device_count)
        ]

        merchant = self._pick_merchant(scenario)
        # An actor starts after its customer joined, and its whole run has to
        # fit inside the window.
        span_days = episodes * behavior.episode_gap_days
        latest_start = self.window_start + timedelta(
            days=max(self.window_days - span_days, 0.5)
        )
        earliest = max(primary.joined_at, self.window_start)
        if latest_start <= earliest:
            clock = earliest
        else:
            clock = datetime.fromtimestamp(
                float(self.rng.uniform(earliest.timestamp(), latest_start.timestamp())),
                tz=UTC,
            )

        instrument = new_instrument(
            self.rng, self.instrument_config, behavior.method_validity
        )
        previous_amount: float | None = None
        session_index = 0
        attempt_index = 0
        used_devices: set[str] = set()
        events: list[dict] = []

        for episode in range(episodes):
            if episode:
                clock += timedelta(
                    days=float(
                        self.rng.uniform(
                            behavior.episode_gap_days * 0.5,
                            behavior.episode_gap_days * 1.5,
                        )
                    )
                )
                if not scenario.merchant_kinds and self.rng.random() < MERCHANT_REDRAW:
                    merchant = self._pick_merchant(scenario)
            clock = self._episode_start(scenario, merchant, clock)

            # Which device this visit happens on. Every device gets its own
            # episode first, so none is left unused.
            if behavior.device_mode == "sticky":
                if episode < len(devices):
                    device = devices[episode]
                elif self.rng.random() < STICKY_SWITCH:
                    device = devices[int(self.rng.integers(0, len(devices)))]
                else:
                    device = devices[-1]
            else:
                device = devices[0]

            session_index += 1
            session = f"{self.prefix}ses_{actor_id}_{session_index}"
            customer = customers[int(self.rng.integers(0, len(customers)))]
            ip = self._draw_ip(customer, behavior.ip_pool)

            # Signed in for the whole visit, or not at all: a shopper does not
            # log in and out between two clicks.
            login_rate = min(
                customer.login_propensity
                * behavior.login_rate
                * login_affinity(self.config["merchants"], merchant.kind),
                1.0,
            )
            logged_in = bool(self.rng.random() < login_rate)

            for attempt in range(behavior.attempts):
                step = behavior.at(attempt_index)
                if attempt:
                    clock += timedelta(
                        seconds=lognormal_gap(
                            self.rng, step.gap_seconds, step.gap_spread
                        )
                    )
                    if self.rng.random() < step.session_rotation:
                        session_index += 1
                        session = f"{self.prefix}ses_{actor_id}_{session_index}"
                    if self.rng.random() < step.ip_rotation:
                        ip = self._draw_ip(customer, behavior.ip_pool)
                    if self.rng.random() >= step.instrument_reuse:
                        instrument = new_instrument(
                            self.rng, self.instrument_config, step.method_validity
                        )
                if behavior.device_mode == "spread":
                    device = devices[attempt_index % len(devices)]

                used_devices.add(device)
                amount = choose_amount(
                    self.rng,
                    merchant,
                    step.amount_style_weights,
                    previous_amount,
                    self.amount_multiplier,
                )
                previous_amount = amount
                request_id = f"{self.prefix}req_{self._next('request'):07d}"
                events.append(
                    blank_event(
                        "authorization_request",
                        clock,
                        f"{self.prefix}evt_{self._next('event'):08d}",
                        request_id=request_id,
                        merchant_id=merchant.merchant_id,
                        customer_id=(customer.customer_id if logged_in else None),
                        device_id=device,
                        session_id=session,
                        ip_fingerprint=ip,
                        amount=amount,
                        currency=self.config["currency"],
                        campaign_active=merchant.in_campaign(clock),
                    )
                )

                approved, cause = resolve_attempt(
                    self.rng, merchant, instrument, step.network_instability
                )
                if cause == "instrument":
                    instrument.declined_before = True
                outcome_time = clock + timedelta(
                    seconds=float(
                        self.rng.uniform(*self.identity["outcome_lag_seconds"])
                    )
                )
                events.append(
                    blank_event(
                        "authorization_outcome",
                        outcome_time,
                        f"{self.prefix}evt_{self._next('event'):08d}",
                        request_id=request_id,
                        device_id=device,
                        session_id=session,
                        authorization_result="approved" if approved else "declined",
                        failure_reason=(
                            None
                            if approved
                            else failure_reason(self.rng, instrument, cause)
                        ),
                        payment_method=instrument.method,
                        card_last4=(
                            instrument.last4 if instrument.method == "card" else None
                        ),
                        card_network=(
                            instrument.network if instrument.method == "card" else None
                        ),
                        card_type=(
                            instrument.card_type
                            if instrument.method == "card"
                            else None
                        ),
                        card_issuer=(
                            instrument.issuer if instrument.method == "card" else None
                        ),
                        international=instrument.international,
                    )
                )
                attempt_index += 1

                if approved:
                    if self.rng.random() < step.checkout_completion:
                        checkout_time = outcome_time + timedelta(
                            seconds=float(
                                self.rng.uniform(*self.identity["checkout_lag_seconds"])
                            )
                        )
                        events.append(
                            blank_event(
                                "checkout_completion",
                                checkout_time,
                                f"{self.prefix}evt_{self._next('event'):08d}",
                                request_id=request_id,
                                device_id=device,
                                session_id=session,
                            )
                        )
                        clock = checkout_time
                    # `continue_after_success` ends the VISIT, not the actor.
                    # A shopper who successfully buys something stops clicking
                    # and comes back next week; the actor's run length is set
                    # by `episodes`. (In v2 this ended the whole run, which in
                    # a multi-episode generator would silently delete every
                    # long-horizon legitimate history.)
                    if self.rng.random() >= step.continue_after_success:
                        break

        # Labels only for devices that actually transacted (v3 fix M6).
        labels = [
            {
                "device_id": device_id,
                "actor_id": actor_id,
                "customer_id": primary.customer_id,
                "merchant_id": merchant.merchant_id,
                "merchant_kind": merchant.kind,
                "population": scenario.population,
                "scenario": scenario.name,
                "label": scenario.label,
                "split": self.split_name,
            }
            for device_id in sorted(used_devices)
        ]
        return events, labels

    # -- the split ---------------------------------------------------------

    def generate(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        target = int(self.split["devices"])
        fraction = float(self.split["benchmark_attack_device_fraction"])
        attack_target = int(round(target * fraction))
        legitimate_target = target - attack_target

        by_population: dict[str, list[ScenarioV3]] = {}
        for scenario in self.scenarios.values():
            by_population.setdefault(scenario.population, []).append(scenario)

        def draw_scenario(population: str) -> ScenarioV3:
            pool = by_population[population]
            weights = np.array([s.weight for s in pool], dtype=float)
            return pool[int(self.rng.choice(len(pool), p=weights / weights.sum()))]

        events: list[dict] = []
        labels: list[dict] = []
        counts = {"attack": 0, "legitimate": 0}
        # Device-level targeting: an actor contributes several devices, so
        # drawing populations per actor overshoots badly.
        while (
            counts["attack"] < attack_target or counts["legitimate"] < legitimate_target
        ):
            if counts["attack"] >= attack_target:
                population = "legitimate"
            elif counts["legitimate"] >= legitimate_target:
                population = "attack"
            else:
                population = "attack" if self.rng.random() < fraction else "legitimate"
            actor_events, actor_labels = self._generate_actor(draw_scenario(population))
            if not actor_labels:  # pragma: no cover - an actor always transacts
                continue
            counts[population] += len(actor_labels)
            events.extend(actor_events)
            labels.extend(actor_labels)

        frame = pd.DataFrame(events, columns=list(EVENT_COLUMNS))
        frame = frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        frame["split"] = self.split_name
        return frame, pd.DataFrame(labels, columns=list(LABEL_COLUMNS))


# --------------------------------------------------------------------------
# dataset assembly
# --------------------------------------------------------------------------


def config_hash(config: dict) -> str:
    return hashlib.sha256(
        yaml.safe_dump(config, sort_keys=True, default_flow_style=False).encode()
    ).hexdigest()


def load_config(path) -> dict:
    return yaml.safe_load(open(path).read())


def _as_datetime(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def generate_dataset_v3(config: dict) -> dict:
    """Both splits: disjoint devices, customers, IPs -- and disjoint in time."""
    merchants = build_covering_merchants(
        np.random.default_rng(int(config["merchants"]["seed"])), config["merchants"]
    )
    splits = config["splits"]

    train_start = _as_datetime(splits["train"]["start"])
    train_generator = GeneratorV3(
        config, "train", splits["train"], merchants, train_start
    )
    train_raw, train_labels = train_generator.generate()

    # Validation opens after the LAST training event, not after a fixed
    # calendar date -- a long-horizon training actor must not bleed across.
    train_last = pd.to_datetime(train_raw.timestamp, format="ISO8601").max()
    gap = float(splits["validation"]["starts_after_train_gap_days"])
    validation_start = train_last.to_pydatetime() + timedelta(days=gap)
    validation_generator = GeneratorV3(
        config, "validation", splits["validation"], merchants, validation_start
    )
    validation_raw, validation_labels = validation_generator.generate()

    raw = pd.concat([train_raw, validation_raw], ignore_index=True)
    raw = raw.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    raw["event_sequence"] = range(1, len(raw) + 1)
    raw["timestamp"] = raw["timestamp"].map(lambda value: value.isoformat())
    labels = pd.concat([train_labels, validation_labels], ignore_index=True)

    return {
        "raw_events": raw,
        "labels": labels,
        "merchants": merchants,
        "windows": {
            "train_start": train_start,
            "train_last_event": train_last.to_pydatetime(),
            "validation_start": validation_start,
        },
    }


def build_manifest(config: dict, bundle: dict) -> dict:
    """Provenance and composition only. No model metric, no policy metric."""
    raw, labels = bundle["raw_events"], bundle["labels"]
    times = pd.to_datetime(raw.timestamp, format="ISO8601")
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    devices = labels.drop_duplicates("device_id")
    merchants = bundle["merchants"]

    per_split = {}
    for name, group in labels.groupby("split"):
        split_requests = requests.loc[requests.split.eq(name)]
        split_times = pd.to_datetime(split_requests.timestamp, format="ISO8601")
        unique = group.drop_duplicates("device_id")
        per_split[str(name)] = {
            "devices": int(unique.device_id.nunique()),
            "customers": int(group.customer_id.nunique()),
            "actors": int(group.actor_id.nunique()),
            "requests": int(len(split_requests)),
            "attack_devices": int(unique.label.eq(1).sum()),
            "legitimate_devices": int(unique.label.eq(0).sum()),
            "realized_attack_device_fraction": round(float(unique.label.mean()), 4),
            "first_event": split_times.min().isoformat(),
            "last_event": split_times.max().isoformat(),
        }

    present = requests.customer_id.notna()
    request_labels = requests.merge(
        devices[["device_id", "label"]], on="device_id", how="left"
    )
    return {
        "dataset_name": config["dataset_name"],
        "generator_version": config["generator_version"],
        "spec_version": SPEC_VERSION,
        "config_sha256": config_hash(config),
        "feature_contract_sha256": MODEL_FEATURES_SHA256,
        "events": int(len(raw)),
        "requests": int(len(requests)),
        "outcomes": int(raw.event_type.eq("authorization_outcome").sum()),
        "checkouts": int(raw.event_type.eq("checkout_completion").sum()),
        "devices": int(devices.device_id.nunique()),
        "customers": int(labels.customer_id.nunique()),
        "actors": int(labels.actor_id.nunique()),
        "merchants": len(merchants),
        "merchant_kinds_declared": sorted(config["merchants"]["kinds"]),
        "merchant_kinds_realized": sorted({m.kind for m in merchants}),
        "merchant_instances_per_kind": {
            kind: sum(1 for m in merchants if m.kind == kind)
            for kind in sorted({m.kind for m in merchants})
        },
        "merchant_kind_devices": {
            str(k): int(v)
            for k, v in devices.groupby("merchant_kind").device_id.nunique().items()
        },
        "scenario_devices": devices.groupby("scenario").device_id.nunique().to_dict(),
        "legitimate_devices": int(devices.label.eq(0).sum()),
        "attack_devices": int(devices.label.eq(1).sum()),
        "customer_id_presence": {
            "overall_request_share": round(float(present.mean()), 4),
            "attack_request_share": round(
                float(
                    request_labels.loc[request_labels.label.eq(1)]
                    .customer_id.notna()
                    .mean()
                ),
                4,
            ),
            "legitimate_request_share": round(
                float(
                    request_labels.loc[request_labels.label.eq(0)]
                    .customer_id.notna()
                    .mean()
                ),
                4,
            ),
            "note": (
                "A synthetic modelling assumption (~65% present in development), "
                "not a claimed industry statistic. Presence is decided per "
                "episode and shaped by the customer, the scenario and the "
                "merchant; guest families force it to zero."
            ),
        },
        "splits": per_split,
        "window": {
            "first_event": times.min().isoformat(),
            "last_event": times.max().isoformat(),
            "train_start": str(bundle["windows"]["train_start"]),
            "validation_start": str(bundle["windows"]["validation_start"]),
        },
        "prevalence_disclosure": (
            "Attack devices are deliberately enriched so every family carries "
            "enough examples for development. This is a SAMPLING CHOICE, not "
            "an estimate of real card-testing prevalence; any precision "
            "measured here is conditional on it."
        ),
        "model_trained": False,
        "blind_evaluated": False,
    }
