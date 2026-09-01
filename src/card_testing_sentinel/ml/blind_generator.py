"""Blind benchmark generator (revision v1.1).

A separate generation path with its own configuration, its own twenty
scenario families and its own merchant population -- deliberately NOT
``generate_development_dataset(mode="blind")``. It shares only the neutral
mechanics in ``ml/primitives.py`` (instruments, gateway outcome resolution,
amount styles, event rows) and the merchant/scenario loaders.

INDEPENDENCE (see docs/blind_spec.md §3). This module must never import
``modeling``, ``policy``, or the training/evaluation modules. It cannot read
a model coefficient, a prediction, a threshold, a feature importance or any
development result -- an import-graph test enforces this. Every shift here
comes from the specification, which was written before the dataset existed.

Blind-only mechanics that the development generator does not have:

* ``dormant_gap_days`` -- a long inactivity gap after the first attempt, so a
  returning customer carries real device age but no recent history.
* ``burst_pause`` -- alternating short bursts and long quiet periods, instead
  of one cadence for the whole run.
* the ``high`` amount style -- genuine big-ticket retries.
* ``merchant_origin`` -- known vs unseen archetype, carried on labels for
  evaluation grouping only. It is not a model feature.

Revision v1.1 (pre-evaluation, no performance observed) corrects the
objective generation defects found by the v1.0 validation run: merchant kinds
were sampled with replacement, so declared kinds -- including the unseen
`ticketing_events` archetype -- could be missing entirely; a scenario whose
declared merchant kinds were all absent silently fell back to the whole
merchant pool; the attack fraction was applied per *actor* while the
evaluation is device-level; and `window.days` named a span it did not bound.
See docs/blind_spec.md §13. No blind performance number was observed before
v1.1 was frozen.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.features.specification import MODEL_FEATURES_SHA256
from card_testing_sentinel.ml.merchants import (
    MerchantProfile,
    make_merchant,
    resolve_calendar,
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
from card_testing_sentinel.ml.scenarios import (
    ScenarioConfig,
    draw_behavior,
    load_scenarios,
)

# The authoritative version is `blind_version` in configs/blind.yaml; this
# constant is the default the generator was written against.
BLIND_VERSION = "v1.1"
IDENTITY_PREFIX = "bld"

LABEL_COLUMNS = (
    "device_id",
    "actor_id",
    "merchant_id",
    "merchant_kind",
    "merchant_origin",
    "population",
    "scenario",
    "label",
)


class BlindBenchmarkError(RuntimeError):
    """Raised when generating would violate the benchmark's own rules."""


def required_merchant_kinds(config: dict) -> tuple[str, ...]:
    """Every merchant kind the blind specification declares.

    All of them are required: an archetype that is declared but never realized
    is a hole in the benchmark, and in v1.0 it silently removed
    `ticketing_events` -- one of the three unseen kinds -- from the data.
    """
    return tuple(sorted(config["merchants"]["kinds"]))


def build_blind_merchants(
    rng: np.random.Generator, config: dict
) -> list[MerchantProfile]:
    """Allocate merchant instances so every declared kind is realized.

    Each declared kind gets one instance first; any remaining slots are then
    drawn by the configured weights. This is a coverage guarantee, not a
    difficulty choice -- no model or policy result informs it.
    """
    kinds = config["kinds"]
    names = sorted(kinds)
    count = int(config["count"])
    if count < len(names):
        raise BlindBenchmarkError(
            f"the blind config declares {len(names)} merchant kinds but only "
            f"{count} merchant slots; every declared kind must be realized"
        )
    weights = np.array([float(kinds[name]["weight"]) for name in names])
    extra = list(rng.choice(names, size=count - len(names), p=weights / weights.sum()))
    calendar = resolve_calendar(config)
    return [
        make_merchant(rng, index, str(kind), kinds[kind], calendar)
        for index, kind in enumerate(names + extra)
    ]


class BlindGenerator:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.version = str(config["blind_version"])
        self.seed = int(config["seed"])
        self.rng = np.random.default_rng(self.seed)
        self.scenarios = load_scenarios(config)
        self.merchants = build_blind_merchants(
            np.random.default_rng(int(config["merchants"]["seed"])),
            config["merchants"],
        )
        self.by_kind: dict[str, list[MerchantProfile]] = {}
        for merchant in self.merchants:
            self.by_kind.setdefault(merchant.kind, []).append(merchant)
        missing = sorted(set(required_merchant_kinds(config)) - set(self.by_kind))
        if missing:
            raise BlindBenchmarkError(
                f"declared merchant kinds were not realized: {missing}"
            )
        self.instrument_config = config["instruments"]
        self.identity_config = config["identity"]
        self.shared_ips = [
            f"ip_shared_{index:04d}"
            for index in range(int(self.identity_config["shared_ip_pool"]))
        ]
        self._counters = {"event": 0, "request": 0, "actor": 0, "device": 0}
        #: First event timestamp of each generated actor, for window reporting.
        self.actor_starts: list[datetime] = []

    # -- helpers -----------------------------------------------------------

    def _next(self, kind: str) -> int:
        self._counters[kind] += 1
        return self._counters[kind]

    def _pick_merchant(self, scenario: ScenarioConfig) -> MerchantProfile:
        """Pick a merchant the scenario is actually compatible with.

        A scenario that declares merchant kinds means it: `campaign_rush`
        belongs on campaign-heavy merchants. In v1.0 an empty pool silently
        fell back to every merchant, which put campaign families on merchants
        with ordinary campaign schedules and quietly broke the pairing the
        specification describes. Failing loudly is the only safe behaviour.
        """
        if not scenario.merchant_kinds:
            return self.merchants[int(self.rng.integers(0, len(self.merchants)))]
        pool = [
            merchant
            for kind in scenario.merchant_kinds
            for merchant in self.by_kind.get(kind, [])
        ]
        if not pool:
            raise BlindBenchmarkError(
                f"scenario '{scenario.name}' declares merchant kinds "
                f"{list(scenario.merchant_kinds)} but none exists in the "
                "generated merchant population; never fall back to the full pool"
            )
        return pool[int(self.rng.integers(0, len(pool)))]

    # -- one actor ---------------------------------------------------------

    def _generate_actor(
        self, scenario: ScenarioConfig, window_start: datetime, window_days: int
    ) -> tuple[list[dict], list[dict]]:
        behavior = draw_behavior(self.rng, scenario)
        merchant = self._pick_merchant(scenario)

        actor_id = f"act_{self._next('actor'):06d}"
        devices = [
            f"dev_{self._next('device'):06d}" for _ in range(behavior.device_pool)
        ]
        customers = [
            f"cus_{actor_id}_{index}" for index in range(behavior.customer_pool)
        ]
        owned_ips = [
            f"ip_{actor_id}_{index}" for index in range(int(self.rng.integers(2, 8)))
        ]

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
                        float(self.rng.uniform(low, high)), tz=UTC
                    )

        # A dormant returning customer starts early enough in the window that
        # its long inactivity gap still lands inside the benchmark.
        dormant_days = 0.0
        if scenario.dormant_gap_days[1] > 0:
            dormant_days = float(self.rng.uniform(*scenario.dormant_gap_days))
            usable = max(window_days - dormant_days, 1.0)
            clock = window_start + timedelta(
                seconds=float(self.rng.uniform(0, usable * 86400 * 0.5))
            )

        burst = scenario.burst_pause
        burst_length = int(self.rng.integers(*burst["burst_length"])) if burst else 0

        device = devices[0]
        customer = customers[0]
        session_index = 0
        session = f"ses_{actor_id}_0"
        ip = draw_ip()
        instrument = new_instrument(
            self.rng, self.instrument_config, behavior.method_validity
        )
        previous_amount: float | None = None

        events: list[dict] = []
        for attempt in range(behavior.attempts):
            step = behavior.at(attempt)
            if attempt:
                if dormant_days and attempt == 1:
                    # the long sleep: real device age, no recent activity
                    clock += timedelta(days=dormant_days)
                elif burst and burst_length and attempt % burst_length == 0:
                    clock += timedelta(
                        seconds=float(self.rng.uniform(*burst["pause_seconds"]))
                    )
                else:
                    clock += timedelta(
                        seconds=lognormal_gap(
                            self.rng, step.gap_seconds, step.gap_spread
                        )
                    )
                if self.rng.random() < step.session_rotation:
                    session_index += 1
                    session = f"ses_{actor_id}_{session_index}"
                if self.rng.random() < step.ip_rotation:
                    ip = draw_ip()
                if len(devices) > 1 and self.rng.random() < 0.45:
                    device = devices[int(self.rng.integers(0, len(devices)))]
                if len(customers) > 1 and self.rng.random() < 0.5:
                    customer = customers[int(self.rng.integers(0, len(customers)))]
                if self.rng.random() >= step.instrument_reuse:
                    instrument = new_instrument(
                        self.rng, self.instrument_config, step.method_validity
                    )

            amount = choose_amount(
                self.rng, merchant, step.amount_style_weights, previous_amount
            )
            previous_amount = amount
            request_id = f"req_{self._next('request'):07d}"

            events.append(
                blank_event(
                    "authorization_request",
                    clock,
                    f"evt_{self._next('event'):08d}",
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
                self.rng, merchant, instrument, step.network_instability
            )
            if cause == "instrument":
                instrument.declined_before = True
            outcome_time = clock + timedelta(
                seconds=float(
                    self.rng.uniform(*self.identity_config["outcome_lag_seconds"])
                )
            )
            events.append(
                blank_event(
                    "authorization_outcome",
                    outcome_time,
                    f"evt_{self._next('event'):08d}",
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
                        instrument.card_type if instrument.method == "card" else None
                    ),
                    card_issuer=(
                        instrument.issuer if instrument.method == "card" else None
                    ),
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
                        blank_event(
                            "checkout_completion",
                            checkout_time,
                            f"evt_{self._next('event'):08d}",
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
                "merchant_origin": merchant.origin,
                "population": scenario.population,
                "scenario": scenario.name,
                "label": scenario.label,
            }
            for device_id in devices
        ]
        return events, labels

    # -- the benchmark -----------------------------------------------------

    def generate(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        window = self.config["window"]
        start = window["start"]
        start = (
            start if isinstance(start, datetime) else datetime.fromisoformat(str(start))
        )
        # Actors *start* inside this window. Long-horizon families
        # (ultra_patient_tester, sparse_multiday, dormant_returning_customer)
        # legitimately continue past its end; truncating them to force every
        # event inside the window would delete the behaviour the benchmark
        # exists to test.
        days = int(window["actor_start_window_days"])
        target = int(self.config["population"]["devices"])
        attack_fraction = float(
            self.config["population"]["benchmark_attack_device_fraction"]
        )
        attack_target = int(round(target * attack_fraction))
        legitimate_target = target - attack_target

        by_population: dict[str, list[ScenarioConfig]] = {}
        for scenario in self.scenarios.values():
            by_population.setdefault(scenario.population, []).append(scenario)

        def draw_scenario(population: str) -> ScenarioConfig:
            pool = by_population[population]
            weights = np.array([s.weight for s in pool], dtype=float)
            return pool[int(self.rng.choice(len(pool), p=weights / weights.sum()))]

        events: list[dict] = []
        labels: list[dict] = []
        self.actor_starts = []
        counts = {"attack": 0, "legitimate": 0}
        # Device-level targets. An actor contributes several devices, and
        # blind attack actors own 4-9 of them, so drawing populations at the
        # actor level (v1.0) overshot the intended device prevalence badly.
        while (
            counts["attack"] < attack_target or counts["legitimate"] < legitimate_target
        ):
            if counts["attack"] >= attack_target:
                population = "legitimate"
            elif counts["legitimate"] >= legitimate_target:
                population = "attack"
            else:
                population = (
                    "attack" if self.rng.random() < attack_fraction else "legitimate"
                )
            actor_events, actor_labels = self._generate_actor(
                draw_scenario(population), start, days
            )
            counts[population] += len(actor_labels)
            self.actor_starts.append(min(row["timestamp"] for row in actor_events))
            events.extend(actor_events)
            labels.extend(actor_labels)

        frame = pd.DataFrame(events, columns=list(EVENT_COLUMNS))
        # Global time order then sequential numbering guarantees that, for any
        # single device, (timestamp, event_sequence) is non-decreasing -- what
        # the runtime engine's per-device ordering check requires.
        frame = frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        frame["event_sequence"] = range(1, len(frame) + 1)
        frame["timestamp"] = frame["timestamp"].map(lambda value: value.isoformat())

        label_frame = pd.DataFrame(labels, columns=list(LABEL_COLUMNS))
        # Namespace every actor-owned identity so it can never collide with a
        # development one.
        for column in (
            "event_id",
            "request_id",
            "device_id",
            "session_id",
            "customer_id",
            "ip_fingerprint",
            "merchant_id",
        ):
            frame[column] = frame[column].map(
                lambda value: None if pd.isna(value) else f"{IDENTITY_PREFIX}_{value}"
            )
        for column in ("device_id", "actor_id", "merchant_id"):
            label_frame[column] = label_frame[column].map(
                lambda value: f"{IDENTITY_PREFIX}_{value}"
            )
        return frame, label_frame


# --------------------------------------------------------------------------
# guards, hashing and the bundle
# --------------------------------------------------------------------------


def config_hash(config: dict) -> str:
    return hashlib.sha256(
        yaml.safe_dump(config, sort_keys=True, default_flow_style=False).encode()
    ).hexdigest()


def assert_not_consumed(freeze_manifest: Path) -> None:
    """Refuse to regenerate a benchmark whose results have been observed.

    Once a blind metric exists, the benchmark is spent: regenerating it would
    silently give the system a second look at a 'held-out' set.
    """
    if not freeze_manifest.is_file():
        raise BlindBenchmarkError(
            "the freeze manifest is missing; freeze the benchmark before generating"
        )
    manifest = json.loads(freeze_manifest.read_text())
    if manifest.get("consumed") or manifest.get("blind_evaluated"):
        raise BlindBenchmarkError(
            f"blind {manifest.get('blind_version')} has already been evaluated and is "
            "consumed. Do not regenerate or overwrite it -- create a new blind "
            "version with a new seed and a spec revision instead."
        )


def assert_after_development(
    frame: pd.DataFrame, development_manifest: Path, floor: datetime
) -> dict:
    """Hard temporal separation: every blind event must follow every
    development event."""
    blind_first = pd.to_datetime(frame.timestamp, format="ISO8601").min()
    if blind_first.to_pydatetime() < floor:
        raise BlindBenchmarkError(
            f"blind window opens at {blind_first}, before the configured floor {floor}"
        )
    manifest = json.loads(development_manifest.read_text())
    last_development = max(
        datetime.fromisoformat(split["last_event"])
        for split in manifest["splits"].values()
    )
    if blind_first.to_pydatetime() <= last_development:
        raise BlindBenchmarkError(
            f"blind starts at {blind_first} but development ends at "
            f"{last_development}; the windows must not overlap"
        )
    return {
        "development_last_event": last_development.isoformat(),
        "blind_first_event": blind_first.isoformat(),
        "separation_days": round(
            (blind_first.to_pydatetime() - last_development).total_seconds() / 86400, 3
        ),
    }


def build_manifest(
    config: dict,
    frame: pd.DataFrame,
    labels: pd.DataFrame,
    merchants: list[MerchantProfile],
    spec_path: Path,
    separation: dict,
    actor_starts: list[datetime],
) -> dict:
    """Provenance only. No model metric, no prediction, no policy metric."""
    times = pd.to_datetime(frame.timestamp, format="ISO8601")
    requests = frame.loc[frame.event_type.eq("authorization_request")]
    origins = labels.drop_duplicates("merchant_id").groupby("merchant_origin").size()
    devices = labels.drop_duplicates("device_id")
    request_labels = requests.merge(
        devices[["device_id", "label"]], on="device_id", how="left"
    )
    actors = labels.drop_duplicates("actor_id")
    starts = sorted(actor_starts)
    kind_devices = devices.groupby("merchant_kind").device_id.nunique()
    kind_requests = (
        requests.merge(
            devices[["device_id", "merchant_kind"]], on="device_id", how="left"
        )
        .groupby("merchant_kind")
        .size()
    )
    return {
        "blind_version": str(config["blind_version"]),
        "dataset_name": config["dataset_name"],
        "generator_version": config["generator_version"],
        "blind_config_sha256": config_hash(config),
        "blind_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "feature_contract_sha256": MODEL_FEATURES_SHA256,
        "seed": int(config["seed"]),
        "merchant_seed": int(config["merchants"]["seed"]),
        "events": int(len(frame)),
        "requests": int(len(requests)),
        "outcomes": int(frame.event_type.eq("authorization_outcome").sum()),
        "checkouts": int(frame.event_type.eq("checkout_completion").sum()),
        "devices": int(labels.device_id.nunique()),
        "merchants": int(labels.merchant_id.nunique()),
        "merchant_origin_counts": {
            str(key): int(value) for key, value in origins.items()
        },
        "configured_merchant_kinds": list(required_merchant_kinds(config)),
        "realized_merchant_kinds": sorted({m.kind for m in merchants}),
        "merchant_instances_per_kind": {
            kind: sum(1 for m in merchants if m.kind == kind)
            for kind in sorted({m.kind for m in merchants})
        },
        "merchant_kind_devices": {
            str(kind): int(value) for kind, value in kind_devices.items()
        },
        "merchant_kind_requests": {
            str(kind): int(value) for kind, value in kind_requests.items()
        },
        "scenario_devices": labels.groupby("scenario").device_id.nunique().to_dict(),
        "scenario_requests": (
            requests.merge(
                labels[["device_id", "scenario"]].drop_duplicates("device_id"),
                on="device_id",
                how="left",
            )
            .groupby("scenario")
            .size()
            .to_dict()
        ),
        "legitimate_devices": int(labels.loc[labels.label.eq(0)].device_id.nunique()),
        "attack_devices": int(labels.loc[labels.label.eq(1)].device_id.nunique()),
        # Configured target is device-level, because the evaluation is
        # device-level. Realized figures are reported separately and are not
        # assumed to agree: an actor owns several devices and makes a variable
        # number of requests, so the three fractions genuinely differ.
        "configured_attack_device_fraction": float(
            config["population"]["benchmark_attack_device_fraction"]
        ),
        "realized_attack_device_fraction": round(float(devices.label.eq(1).mean()), 4),
        "realized_attack_request_fraction": round(
            float(request_labels.label.eq(1).mean()), 4
        ),
        "realized_attack_actor_fraction": round(float(actors.label.eq(1).mean()), 4),
        "window": {
            "configured_start": str(config["window"]["start"]),
            # Actors START inside this window; long-horizon families continue
            # past its end by design.
            "actor_start_window_days": int(config["window"]["actor_start_window_days"]),
            "first_actor_start": starts[0].isoformat() if starts else None,
            "last_actor_start": starts[-1].isoformat() if starts else None,
            "actors": len(starts),
            "first_event": times.min().isoformat(),
            "last_event": times.max().isoformat(),
            "realized_event_span_days": round(
                float((times.max() - times.min()).total_seconds() / 86400), 3
            ),
            "note": (
                "`actor_start_window_days` bounds when actors BEGIN, not when "
                "the benchmark ends. ultra_patient_tester, sparse_multiday and "
                "dormant_returning_customer run for days-to-months after their "
                "start, so the realized event span is longer on purpose. "
                "Truncating them would delete the long-horizon behaviour the "
                "benchmark exists to test."
            ),
        },
        "temporal_separation": separation,
        "prevalence_disclosure": (
            "The blind benchmark attack fraction is a SAMPLING CHOICE so that "
            "every attack family carries enough devices to report per-family "
            "recall. It is not an estimate of real card-testing prevalence, and "
            "any precision computed on it is conditional on this sampling."
        ),
        "contains_model_metrics": False,
        "contains_policy_metrics": False,
        "blind_evaluated": False,
    }


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def generate_blind_bundle(
    config: dict, spec_path: Path, development_manifest: Path
) -> dict:
    generator = BlindGenerator(config)
    frame, labels = generator.generate()
    separation = assert_after_development(
        frame,
        development_manifest,
        (
            config["window"]["must_start_after"]
            if isinstance(config["window"]["must_start_after"], datetime)
            else datetime.fromisoformat(str(config["window"]["must_start_after"]))
        ),
    )
    return {
        "raw_events": frame,
        "labels": labels,
        "manifest": build_manifest(
            config,
            frame,
            labels,
            generator.merchants,
            spec_path,
            separation,
            generator.actor_starts,
        ),
    }


def write_blind(bundle: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("raw_events", "labels"):
        bundle[name].to_csv(
            output_dir / f"{name}.csv", index=False, lineterminator="\n"
        )
    (output_dir / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True, default=str) + "\n"
    )
    return bundle["manifest"]
