"""Synthetic raw-event generator (Dataset V2).

Produces *raw lifecycle events* in exactly the shape the live service
understands -- authorization_request, then an optional authorization_outcome,
then an optional checkout_completion. It never computes a model feature:
features come from replaying these events through the runtime
``FeatureEngine`` (see ``features/batch.py``), so there is one implementation
of feature logic in the repository.

How the label is kept out of the observable data
------------------------------------------------
There is no branch anywhere below of the form ``if attack: ...``. The only
thing a scenario contributes is a set of *latent parameter ranges*
(``ml/scenarios.py``). An actor draws one value per parameter, and every
observable -- gap, amount, session churn, IP churn, approval -- is derived
from those draws plus the merchant profile. Because the ranges overlap
across populations, an unlucky shopper and a patient tester can draw the
same parameters and produce the same events.

Approval in particular is never keyed on the label. Each attempt is resolved
by cause, in order (see ``_attempt_outcome``):

    unusable instrument        -> decline, cause "instrument"
    already declined for cause -> decline, cause "instrument"
    network_instability        -> decline, cause "network"
    merchant.base_success_rate -> approve, else decline, cause "network"

The cause matters: only an instrument-side decline makes later attempts on
the same instrument more likely to fail, so a flaky network never poisons a
good card. An actor whose ``method_validity`` is low picks unusable
instruments more often and therefore fails more often. Card testing shows up
as a *low method_validity actor with high identity churn*, which is what card
testing actually is -- but `repeated_genuine_failures` draws from an
overlapping range, so the signal is a tendency, not a giveaway.

``campaign_active`` is likewise a property of the merchant and the clock: it
comes from the merchant's own campaign windows, so a flash-sale shopper and
an attacker hiding in the same sale genuinely share the context.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.features.specification import MODEL_FEATURES_SHA256
from card_testing_sentinel.ml.merchants import MerchantProfile, build_merchants
from card_testing_sentinel.ml.primitives import (
    EVENT_COLUMNS,
    INSTRUMENT_REASONS,
    NETWORK_REASONS,
    REPEAT_DECLINE,
    UNUSABLE_SUCCESS,
    Instrument,
)
from card_testing_sentinel.ml.scenarios import (
    Behavior,
    ScenarioConfig,
    draw_behavior,
    load_scenarios,
)

LABEL_COLUMNS = (
    "device_id",
    "actor_id",
    "merchant_id",
    "merchant_kind",
    "population",
    "scenario",
    "label",
)


class DatasetGenerator:
    def __init__(
        self,
        config: dict,
        *,
        seed: int,
        merchants: list[MerchantProfile] | None = None,
    ) -> None:
        self.config = config
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.scenarios = load_scenarios(config)
        # Merchants are shared across splits: validation is "new devices in a
        # later window on the merchants we already know", not a new universe.
        self.merchants = (
            merchants
            if merchants is not None
            else build_merchants(
                np.random.default_rng(int(config["merchants"]["seed"])),
                config["merchants"],
            )
        )
        self.by_kind: dict[str, list[MerchantProfile]] = {}
        for merchant in self.merchants:
            self.by_kind.setdefault(merchant.kind, []).append(merchant)
        self.instrument_config = config["instruments"]
        self.identity_config = config["identity"]
        self.shared_ips = [
            f"ip_shared_{index:04d}"
            for index in range(int(self.identity_config["shared_ip_pool"]))
        ]
        self._counters = {"event": 0, "request": 0, "actor": 0, "device": 0}

    # -- small helpers -----------------------------------------------------

    def _next(self, kind: str) -> int:
        self._counters[kind] += 1
        return self._counters[kind]

    def _pick(self, options, weights) -> str:
        probabilities = np.asarray(weights, dtype=float)
        return str(self.rng.choice(options, p=probabilities / probabilities.sum()))

    def _new_instrument(self, behavior: Behavior) -> Instrument:
        spec = self.instrument_config
        # A small last4 space, so two unrelated instruments collide sometimes.
        # last4 is a weak hint, never an identity.
        return Instrument(
            usable=bool(self.rng.random() < behavior.method_validity),
            method=self._pick(spec["methods"], spec["method_weights"]),
            last4=f"{int(self.rng.integers(0, int(spec['last4_pool']))) % 10000:04d}",
            network=self._pick(spec["networks"], spec["network_weights"]),
            card_type=self._pick(spec["types"], spec["type_weights"]),
            issuer=f"issuer_{int(self.rng.integers(1, int(spec['issuers']) + 1)):02d}",
            international=bool(self.rng.random() < float(spec["international_rate"])),
        )

    def _choose_amount(
        self,
        merchant: MerchantProfile,
        behavior: Behavior,
        previous: float | None,
        multiplier: float,
    ) -> float:
        weights = behavior.amount_style_weights
        styles = sorted(weights)
        style = self._pick(styles, [weights[name] for name in styles])
        if style == "repeat" and previous is not None:
            return previous
        if style == "low":
            # Genuine micro-payments live here too: tips, top-ups, ₹1 verifications.
            return round(float(self.rng.uniform(1.0, 9.0)), 2)
        if style == "varied":
            return merchant.draw_amount(
                self.rng, multiplier * float(self.rng.uniform(0.2, 3.0))
            )
        return merchant.draw_amount(self.rng, multiplier)

    def _attempt_outcome(
        self, merchant: MerchantProfile, behavior: Behavior, instrument: Instrument
    ) -> tuple[bool, str | None]:
        """Resolve one payment, and say *why* it failed.

        The cause matters: a network/gateway failure says nothing about the
        card, so it must not poison an otherwise good instrument. Only an
        instrument-side decline makes later attempts on the same instrument
        more likely to fail.
        """
        if not instrument.usable and self.rng.random() >= UNUSABLE_SUCCESS:
            return False, "instrument"
        if instrument.declined_before and self.rng.random() < REPEAT_DECLINE:
            return False, "instrument"
        if self.rng.random() < behavior.network_instability:
            return False, "network"
        if self.rng.random() < merchant.base_success_rate:
            return True, None
        return False, "network"

    def _failure_reason(self, instrument: Instrument, cause: str) -> str:
        if (
            cause == "instrument"
            and instrument.international
            and self.rng.random() < 0.3
        ):
            return "international_blocked"
        pool = INSTRUMENT_REASONS if cause == "instrument" else NETWORK_REASONS
        return str(self.rng.choice(pool))

    def _next_gap(self, behavior: Behavior) -> float:
        """Lognormal around the actor's base cadence, so every scenario has a
        long tail that reaches into the neighbouring scenarios' ranges."""
        return float(
            max(
                1.0,
                self.rng.lognormal(
                    np.log(max(behavior.gap_seconds, 1.0)), behavior.gap_spread
                ),
            )
        )

    def _pick_merchant(self, scenario: ScenarioConfig) -> MerchantProfile:
        if scenario.merchant_kinds:
            pool = [
                merchant
                for kind in scenario.merchant_kinds
                for merchant in self.by_kind.get(kind, [])
            ] or self.merchants
        else:
            pool = self.merchants
        return pool[int(self.rng.integers(0, len(pool)))]

    # -- one actor ---------------------------------------------------------

    def _generate_actor(
        self,
        scenario: ScenarioConfig,
        window_start: datetime,
        window_days: int,
        shift: dict,
    ) -> tuple[list[dict], list[dict]]:
        behavior = draw_behavior(
            self.rng,
            scenario,
            gap_multiplier=float(shift.get("gap_multiplier", 1.0)),
            attempts_bonus=int(shift.get("attempts_bonus", 0)),
        )
        merchant = self._pick_merchant(scenario)
        amount_multiplier = float(shift.get("amount_multiplier", 1.0))

        actor_id = f"act_{self._next('actor'):06d}"
        devices = [
            f"dev_{self._next('device'):06d}" for _ in range(behavior.device_pool)
        ]
        customers = [
            f"cus_{actor_id}_{index}" for index in range(behavior.customer_pool)
        ]
        owned_ips = [
            f"ip_{actor_id}_{index}" for index in range(int(self.rng.integers(2, 7)))
        ]
        # An actor is on a shared egress if its scenario says so, or if this
        # merchant simply pushes a lot of traffic through one network.
        on_shared_ip = (
            behavior.ip_pool == "shared"
            or self.rng.random() < merchant.shared_ip_pressure
        )

        def draw_ip() -> str:
            if on_shared_ip:
                return self.shared_ips[int(self.rng.integers(0, len(self.shared_ips)))]
            return owned_ips[int(self.rng.integers(0, len(owned_ips)))]

        window_end = window_start + timedelta(days=window_days)
        clock = window_start + timedelta(
            seconds=float(self.rng.uniform(0, window_days * 86400))
        )
        if scenario.prefers_campaign:
            # Flash-sale traffic -- shopper and camouflaged attacker alike --
            # should arrive while the merchant is actually running a sale.
            live = [
                (opens, closes)
                for opens, closes in merchant.campaign_windows
                if opens < window_end and closes > window_start
            ]
            if live:
                opens, closes = live[int(self.rng.integers(0, len(live)))]
                low = max(opens, window_start).timestamp()
                high = min(closes, window_end).timestamp()
                if high > low:
                    clock = datetime.fromtimestamp(
                        float(self.rng.uniform(low, high)), tz=window_start.tzinfo
                    )

        device = devices[0]
        customer = customers[0]
        session = f"ses_{actor_id}_0"
        session_index = 0
        ip = draw_ip()
        instruments = [self._new_instrument(behavior)]
        instrument = instruments[0]
        previous_amount: float | None = None

        events: list[dict] = []
        for attempt in range(behavior.attempts):
            step = behavior.at(attempt)
            if attempt:
                clock += timedelta(seconds=self._next_gap(step))
                if self.rng.random() < step.session_rotation:
                    session_index += 1
                    session = f"ses_{actor_id}_{session_index}"
                if self.rng.random() < step.ip_rotation:
                    ip = draw_ip()
                if len(devices) > 1 and self.rng.random() < 0.35:
                    device = devices[int(self.rng.integers(0, len(devices)))]
                if len(customers) > 1 and self.rng.random() < 0.5:
                    customer = customers[int(self.rng.integers(0, len(customers)))]
                if self.rng.random() >= step.instrument_reuse:
                    instrument = self._new_instrument(step)
                    instruments.append(instrument)

            amount = self._choose_amount(
                merchant, step, previous_amount, amount_multiplier
            )
            previous_amount = amount
            request_id = f"req_{self._next('request'):07d}"

            events.append(
                self._event(
                    "authorization_request",
                    clock,
                    request_id=request_id,
                    merchant_id=merchant.merchant_id,
                    customer_id=customer,
                    device_id=device,
                    session_id=session,
                    ip_fingerprint=ip,
                    amount=amount,
                    currency=self.config["currency"],
                    # Campaign context belongs to the merchant and the clock,
                    # not to the actor: everyone transacting during a sale sees
                    # the same flag, attacker and shopper alike.
                    campaign_active=merchant.in_campaign(clock),
                )
            )

            approved, cause = self._attempt_outcome(merchant, step, instrument)
            if cause == "instrument":
                instrument.declined_before = True
            outcome_time = clock + timedelta(
                seconds=float(
                    self.rng.uniform(*self.identity_config["outcome_lag_seconds"])
                )
            )
            events.append(
                self._event(
                    "authorization_outcome",
                    outcome_time,
                    request_id=request_id,
                    device_id=device,
                    session_id=session,
                    authorization_result="approved" if approved else "declined",
                    failure_reason=(
                        None if approved else self._failure_reason(instrument, cause)
                    ),
                    payment_method=instrument.method,
                    card_last4=instrument.last4
                    if instrument.method == "card"
                    else None,
                    card_network=instrument.network
                    if instrument.method == "card"
                    else None,
                    card_type=instrument.card_type
                    if instrument.method == "card"
                    else None,
                    card_issuer=instrument.issuer
                    if instrument.method == "card"
                    else None,
                    international=instrument.international,
                )
            )

            if approved:
                if self.rng.random() < step.checkout_completion:
                    checkout_time = outcome_time + timedelta(
                        seconds=float(
                            self.rng.uniform(
                                *self.identity_config["checkout_lag_seconds"]
                            )
                        )
                    )
                    events.append(
                        self._event(
                            "checkout_completion",
                            checkout_time,
                            request_id=request_id,
                            device_id=device,
                            session_id=session,
                        )
                    )
                    clock = checkout_time
                if self.rng.random() >= step.continue_after_success:
                    break

        labels = [
            {
                "device_id": device_id,
                "actor_id": actor_id,
                "merchant_id": merchant.merchant_id,
                "merchant_kind": merchant.kind,
                "population": scenario.population,
                "scenario": scenario.name,
                "label": scenario.label,
            }
            for device_id in devices
        ]
        return events, labels

    def _event(self, event_type: str, timestamp: datetime, **fields) -> dict:
        row = dict.fromkeys(EVENT_COLUMNS)
        row["event_id"] = f"evt_{self._next('event'):08d}"
        row["event_type"] = event_type
        row["timestamp"] = timestamp
        row.update(fields)
        return row

    # -- one split ---------------------------------------------------------

    def generate_split(
        self, split: dict, start: datetime
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        target_devices = int(split["devices"])
        attack_fraction = float(split["benchmark_attack_fraction"])
        shift = dict(split.get("shift") or {})
        days = int(split["days"])

        by_population: dict[str, list[ScenarioConfig]] = {}
        for scenario in self.scenarios.values():
            by_population.setdefault(scenario.population, []).append(scenario)

        def draw_scenario(population: str) -> ScenarioConfig:
            pool = by_population[population]
            weights = np.array([scenario.weight for scenario in pool], dtype=float)
            index = int(self.rng.choice(len(pool), p=weights / weights.sum()))
            return pool[index]

        events: list[dict] = []
        labels: list[dict] = []
        while len({row["device_id"] for row in labels}) < target_devices:
            population = (
                "attack" if self.rng.random() < attack_fraction else "legitimate"
            )
            actor_events, actor_labels = self._generate_actor(
                draw_scenario(population), start, days, shift
            )
            events.extend(actor_events)
            labels.extend(actor_labels)

        frame = pd.DataFrame(events, columns=list(EVENT_COLUMNS))
        # Sorting globally by time and then numbering guarantees that, for any
        # single device, (timestamp, event_sequence) is non-decreasing -- which
        # is exactly what the engine's per-device ordering check requires.
        frame = frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        frame["event_sequence"] = range(1, len(frame) + 1)
        frame["timestamp"] = frame["timestamp"].map(lambda value: value.isoformat())
        return frame, pd.DataFrame(labels, columns=list(LABEL_COLUMNS))


#: Recorded in the manifest so any figure computed on this dataset carries
#: the caveat with it.
PREVALENCE_DISCLOSURE = (
    "This development dataset intentionally enriches abusive actors so that "
    "every attack subtype has enough examples for model development. The "
    "benchmark attack fraction is a sampling choice, NOT an estimate of how "
    "common card testing is in real merchant traffic. Aggregate precision "
    "measured here is conditional on the synthetic benchmark prevalence and "
    "must not be read as expected production precision. Prefer "
    "prevalence-independent measures -- per-attack-scenario recall and "
    "per-legitimate-scenario false-positive rate -- which the labels table "
    "retains the grouping columns to support."
)


def config_hash(config: dict) -> str:
    return hashlib.sha256(
        yaml.safe_dump(config, sort_keys=True, default_flow_style=False).encode()
    ).hexdigest()


def scenario_profile(raw: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Devices, requests, events and attempts-per-device for each scenario,
    plus each scenario's share of its own population's requests."""
    device_scenario = labels[["device_id", "scenario", "population"]].drop_duplicates(
        "device_id"
    )
    tagged = raw.merge(device_scenario, on="device_id", how="left")
    requests = tagged.loc[tagged.event_type.eq("authorization_request")]
    outcomes = tagged.loc[tagged.event_type.eq("authorization_outcome")]

    profile = pd.DataFrame(
        {
            "population": device_scenario.groupby("scenario").population.first(),
            "devices": device_scenario.groupby("scenario").size(),
            "requests": requests.groupby("scenario").size(),
            "events": tagged.groupby("scenario").size(),
            "checkouts": tagged.loc[tagged.event_type.eq("checkout_completion")]
            .groupby("scenario")
            .size(),
            "declines": outcomes.loc[outcomes.authorization_result.eq("declined")]
            .groupby("scenario")
            .size(),
            "outcomes": outcomes.groupby("scenario").size(),
        }
    ).fillna(0)
    profile["mean_attempts_per_device"] = (profile.requests / profile.devices).round(3)
    profile["decline_rate"] = (profile.declines / profile.outcomes.clip(lower=1)).round(
        4
    )
    population_requests = profile.groupby("population").requests.transform("sum")
    profile["share_of_population_requests"] = (
        profile.requests / population_requests
    ).round(4)
    profile["share_of_population_devices"] = (
        profile.devices / profile.groupby("population").devices.transform("sum")
    ).round(4)
    return profile.astype(
        {
            "devices": int,
            "requests": int,
            "events": int,
            "checkouts": int,
            "declines": int,
            "outcomes": int,
        }
    ).sort_index()


def generate_development_dataset(config: dict) -> dict[str, pd.DataFrame | dict]:
    """Generate the train and validation splits.

    Each split gets its own seed, its own generator instance (so device and
    request counters restart independently) and its own time window. The
    blind set is deliberately NOT produced here.
    """
    merchants = build_merchants(
        np.random.default_rng(int(config["merchants"]["seed"])), config["merchants"]
    )
    frames, label_frames, assignments = [], [], []
    per_split_counts = {}
    resolved_start: datetime | None = None
    for split_name in ("train", "validation"):
        split = config["splits"][split_name]
        if split_name == "train":
            configured = split["start"]
            resolved_start = (
                configured
                if isinstance(configured, datetime)
                else datetime.fromisoformat(str(configured))
            )
        else:
            # Validation opens strictly after the LAST training event, not
            # after the nominal training window: long-horizon actors (patient
            # testers, subscription dunning) run for weeks past their start,
            # and letting those tails bleed into validation would make the
            # temporal-separation claim false.
            train_last = (
                pd.to_datetime(frames[0].timestamp, format="ISO8601")
                .max()
                .to_pydatetime()
            )
            resolved_start = train_last + timedelta(
                days=float(split["starts_after_train_gap_days"])
            )
        generator = DatasetGenerator(
            config, seed=int(split["seed"]), merchants=merchants
        )
        events, labels = generator.generate_split(split, resolved_start)
        # Split-unique identifier prefixes for everything an actor owns: two
        # independently seeded runs must never share a device, request, event
        # or network identity. `merchant_id` is deliberately NOT prefixed --
        # the same merchants appear in both windows.
        prefix = split_name[:3]
        for column in (
            "event_id",
            "request_id",
            "device_id",
            "session_id",
            "customer_id",
            "ip_fingerprint",
        ):
            events[column] = events[column].map(
                lambda value, p=prefix: None if pd.isna(value) else f"{p}_{value}"
            )
        for column in ("device_id", "actor_id"):
            labels[column] = labels[column].map(lambda value, p=prefix: f"{p}_{value}")

        events["split"] = split_name
        labels["split"] = split_name
        frames.append(events)
        label_frames.append(labels)
        assignments.append(labels[["device_id", "split"]])
        observed = pd.to_datetime(events.timestamp, format="ISO8601")
        per_split_counts[split_name] = {
            "devices": int(labels.device_id.nunique()),
            "events": int(len(events)),
            "requests": int(events.event_type.eq("authorization_request").sum()),
            "attack_devices": int(labels.loc[labels.label.eq(1)].device_id.nunique()),
            "arrivals_window_start": resolved_start.isoformat(),
            "arrivals_window_days": int(split["days"]),
            "first_event": observed.min().isoformat(),
            "last_event": observed.max().isoformat(),
            "seed": int(split["seed"]),
            "benchmark_attack_fraction": float(split["benchmark_attack_fraction"]),
        }

    raw = pd.concat(frames, ignore_index=True)
    labels = pd.concat(label_frames, ignore_index=True)
    splits = pd.concat(assignments, ignore_index=True)

    manifest = {
        "dataset_name": config["dataset_name"],
        "generator_version": config["generator_version"],
        "config_sha256": config_hash(config),
        "feature_contract_sha256": MODEL_FEATURES_SHA256,
        "seeds": {name: counts["seed"] for name, counts in per_split_counts.items()},
        "events": int(len(raw)),
        "requests": int(raw.event_type.eq("authorization_request").sum()),
        "outcomes": int(raw.event_type.eq("authorization_outcome").sum()),
        "checkouts": int(raw.event_type.eq("checkout_completion").sum()),
        "devices": int(labels.device_id.nunique()),
        "merchants": int(labels.merchant_id.nunique()),
        "legitimate_devices": int(labels.loc[labels.label.eq(0)].device_id.nunique()),
        "attack_devices": int(labels.loc[labels.label.eq(1)].device_id.nunique()),
        "scenario_devices": labels.groupby("scenario").device_id.nunique().to_dict(),
        "merchant_kind_devices": (
            labels.groupby("merchant_kind").device_id.nunique().to_dict()
        ),
        "scenario_profile": scenario_profile(raw, labels).to_dict("index"),
        "campaign_request_share": round(
            float(
                raw.loc[raw.event_type.eq("authorization_request"), "campaign_active"]
                .astype(bool)
                .mean()
            ),
            4,
        ),
        "splits": per_split_counts,
        "prevalence_disclosure": PREVALENCE_DISCLOSURE,
        "model_trained": False,
    }
    return {
        "raw_events": raw,
        "labels": labels,
        "split_assignments": splits,
        "manifest": manifest,
    }


def load_config(path) -> dict:
    return yaml.safe_load(path.read_text())


def write_dataset(bundle: dict, output_dir) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("raw_events", "labels", "split_assignments"):
        bundle[name].to_csv(
            output_dir / f"{name}.csv", index=False, lineterminator="\n"
        )
    (output_dir / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True, default=str) + "\n"
    )
    return bundle["manifest"]
