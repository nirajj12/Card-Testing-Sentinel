"""Dataset v4 generator -- Post-Blind Development Corpus.

Engineered to resolve the primary failure modes exposed in Blind v2:
1. Generates hard legitimate repeated-failure scenarios (subscription dunning,
   persistent card problems, network retry storms) with identical card numbers
   and long clean customer tenure.
2. Generates distributed and weak-guest card testing campaigns with 100%
   card diversity and rapid proxy / session churn.
3. Generates 20 matched counterfactual twin pairs for causal CPOA evaluation.
4. Guarantees >= 250-300 devices per critical scenario family.
5. Models 20 merchants across 6 business archetypes.
6. Diversifies Blind-v2 covariate shifts across customer age, device age,
   session age, and cadence variability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.ml.merchants import MerchantProfile, make_merchant, resolve_calendar
from card_testing_sentinel.ml.population_v3 import CustomerProfile, build_customers, login_affinity
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
from card_testing_sentinel.ml.scenarios_v4 import CRITICAL_SCENARIOS, SCENARIOS_V4, ScenarioV4

SPEC_VERSION = "v4-postblind"
IDENTITY_PREFIX = "v4"

LABEL_COLUMNS = (
    "device_id",
    "actor_id",
    "leakage_group_id",
    "customer_id",
    "merchant_id",
    "merchant_kind",
    "population",
    "scenario",
    "label",
    "split",
    "counterfactual_pair_id",
    "counterfactual_role",
)


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def build_merchants_v4(config: dict) -> list[MerchantProfile]:
    spec = config["merchants"]
    kinds = spec["kinds"]
    names = sorted(kinds)
    count = int(spec["count"])
    rng = np.random.default_rng(int(spec["seed"]))

    weights = np.array([float(kinds[name]["weight"]) for name in names])
    extras = list(rng.choice(names, size=max(0, count - len(names)), p=weights / weights.sum()))
    calendar = resolve_calendar(spec)
    merchants = []
    for index, kind in enumerate(names + extras):
        merchant = make_merchant(rng, index, str(kind), kinds[kind], calendar)
        merchants.append(
            replace(merchant, merchant_id=f"{IDENTITY_PREFIX}_mer_{index + 1:03d}")
        )
    return merchants


class GeneratorV4:
    """One split of Dataset v4."""

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
        self.prefix = f"{split_name[0]}4_"
        self.rng = np.random.default_rng(int(split_config["seed"]))
        self.scenarios = SCENARIOS_V4
        self.merchants = merchants
        self.by_kind: dict[str, list[MerchantProfile]] = {}
        for merchant in merchants:
            self.by_kind.setdefault(merchant.kind, []).append(merchant)

        self.window_start = window_start
        self.window_days = int(split_config["days"])
        target_devices = int(split_config["devices"])

        self.customers = build_customers(
            np.random.default_rng(int(split_config["seed"]) + 77),
            config,
            count=target_devices + 4000,
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

    def _next(self, kind: str) -> int:
        self._counters[kind] += 1
        return self._counters[kind]

    def _take_customers(self, count: int) -> list[CustomerProfile]:
        if self._customer_cursor + count > len(self.customers):
            # Reset cursor or loop around safely
            self._customer_cursor = 0
        taken = self.customers[self._customer_cursor : self._customer_cursor + count]
        self._customer_cursor += count
        return list(taken)

    def _pick_merchant(self, scenario: ScenarioV4) -> MerchantProfile:
        if not scenario.merchant_kinds:
            return self.merchants[int(self.rng.integers(0, len(self.merchants)))]
        pool = [
            merchant
            for kind in scenario.merchant_kinds
            for merchant in self.by_kind.get(kind, [])
        ]
        if not pool:
            return self.merchants[int(self.rng.integers(0, len(self.merchants)))]
        return pool[int(self.rng.integers(0, len(pool)))]

    def _draw_ip(self, customer: CustomerProfile, pool: str) -> str:
        if pool == "mobile":
            return self.mobile_ips[int(self.rng.integers(0, len(self.mobile_ips)))]
        if pool == "shared" or customer.on_shared_ip:
            return self.shared_ips[int(self.rng.integers(0, len(self.shared_ips)))]
        return customer.home_ips[int(self.rng.integers(0, len(customer.home_ips)))]

    def _generate_actor(
        self,
        scenario: ScenarioV4,
        force_merchant: MerchantProfile | None = None,
        cf_pair_id: str | None = None,
        cf_role: str | None = None,
        shared_surface: dict | None = None,
    ) -> tuple[list[dict], list[dict]]:
        actor_id = f"{self.prefix}act_{self._next('actor'):06d}"
        surface = shared_surface or {}
        device_count = int(surface.get(
            "devices", self.rng.integers(scenario.devices[0], scenario.devices[1] + 1)
        ))
        devices = [
            f"{self.prefix}dev_{self._next('device'):06d}"
            for _ in range(device_count)
        ]

        customer_count = int(
            self.rng.integers(
                scenario.customers_on_device[0], scenario.customers_on_device[1] + 1
            )
        )
        customers = self._take_customers(customer_count)
        primary_customer = customers[0]

        merchant = force_merchant or self._pick_merchant(scenario)
        base_affinity = float(self.config["merchants"]["kinds"][merchant.kind].get("login_affinity", 0.75))
        mult = float(self.rng.uniform(scenario.login_multiplier[0], scenario.login_multiplier[1]))
        is_guest = scenario.guest or (self.rng.random() > (base_affinity * mult))

        # Instrument pool
        instruments: list[Instrument] = []
        if scenario.card_diversity_mode == "single_card":
            # Exact same card across all attempts
            instruments = [
                new_instrument(
                    self.rng,
                    self.instrument_config,
                    float(np.mean(scenario.method_validity)),
                )
            ]
        elif scenario.card_diversity_mode == "wallet_cycle":
            # 2-3 genuine cards
            num_cards = int(self.rng.integers(2, 4))
            instruments = [
                new_instrument(self.rng, self.instrument_config, 1.0)
                for _ in range(num_cards)
            ]
            # Make the first card unusable to trigger genuine wallet switch
            instruments[0].usable = False
        elif scenario.card_diversity_mode == "high_rotation":
            # New card almost every attempt
            pass
        else:
            instruments = [
                new_instrument(
                    self.rng,
                    self.instrument_config,
                    float(np.mean(scenario.method_validity)),
                )
            ]

        # Episode and attempt loop
        events: list[dict] = []
        used_devices: set[str] = set()
        episode_count = int(surface.get(
            "episodes", self.rng.integers(scenario.episodes[0], scenario.episodes[1] + 1)
        ))
        if not surface and scenario.device_mode == "spread":
            episode_count = max(episode_count, device_count)
        
        # Start time
        window_end = self.window_start + timedelta(days=self.window_days)
        start_offset_days = float(self.rng.uniform(0.5, max(1.0, self.window_days - 10.0)))
        current_time = surface.get(
            "start_time", self.window_start + timedelta(days=start_offset_days)
        )

        # Covariate shift: pre-populate customer or device history if established
        history_customers = (
            customers
            if scenario.name == "shared_household_device"
            else ([primary_customer] if scenario.age_pairing == "established_burst" else [])
        )
        for history_customer in history_customers:
            # Material clean tenure: twelve monthly successes for an established
            # account, and three prior successes for each household member.
            history_count = 12 if scenario.age_pairing == "established_burst" else 3
            hist_dev = devices[0]
            used_devices.add(hist_dev)
            hist_card = instruments[0] if instruments else new_instrument(self.rng, self.instrument_config, 1.0)
            hist_card.usable = True
            for hist_index in range(history_count, 0, -1):
                hist_time = current_time - timedelta(days=30 * hist_index)
                hist_req_id = f"{self.prefix}req_{self._next('request'):07d}"
                hist_session = f"{self.prefix}ses_hist_{hist_dev}_{history_customer.customer_id}_{hist_index:02d}"
                common = dict(request_id=hist_req_id, device_id=hist_dev, session_id=hist_session)
                events.append(blank_event(
                    "authorization_request", hist_time,
                    f"{self.prefix}evt_{self._next('event'):08d}",
                    merchant_id=merchant.merchant_id,
                    customer_id=history_customer.customer_id,
                    ip_fingerprint=self._draw_ip(history_customer, "private"),
                    amount=merchant.draw_amount(self.rng), currency="INR",
                    campaign_active=False, **common,
                ))
                events.append(blank_event(
                    "authorization_outcome", hist_time + timedelta(seconds=2),
                    f"{self.prefix}evt_{self._next('event'):08d}",
                    authorization_result="approved", payment_method="card",
                    card_last4=hist_card.last4, card_network=hist_card.network,
                    card_type=hist_card.card_type, card_issuer=hist_card.issuer,
                    international=hist_card.international, **common,
                ))
                events.append(blank_event(
                    "checkout_completion", hist_time + timedelta(seconds=15),
                    f"{self.prefix}evt_{self._next('event'):08d}", **common,
                ))

        repeated_amount = float(surface.get(
            "amount", 499.0 if scenario.name == "subscription_dunning_hard" else merchant.draw_amount(self.rng)
        ))

        for ep_idx in range(episode_count):
            if current_time >= window_end:
                break
            
            # Select device for episode
            if scenario.device_mode == "sticky":
                device_id = devices[0]
            else:
                device_id = devices[ep_idx % len(devices)]
            used_devices.add(device_id)

            session_id = f"{self.prefix}ses_{device_id}_{ep_idx:02d}_{int(self.rng.integers(100, 999))}"
            episode_customer = customers[ep_idx % len(customers)]
            if scenario.name == "cgnat_mobile_ip_storm":
                if ep_idx == 0:
                    actor_shared_ip = self._draw_ip(episode_customer, "mobile")
                ip_addr = actor_shared_ip
            else:
                ip_addr = self._draw_ip(episode_customer, scenario.ip_pool)

            attempt_count = int(surface.get(
                "attempts", self.rng.integers(scenario.attempts[0], scenario.attempts[1] + 1)
            ))
            last_card = instruments[0] if instruments else None

            for att_idx in range(attempt_count):
                if current_time >= window_end:
                    break

                # Paired distributed designs deliberately spread otherwise
                # identical attempts over the shared device count.
                if int(surface.get("devices", 1)) > 1:
                    device_id = devices[att_idx % len(devices)]
                    used_devices.add(device_id)
                    session_id = f"{self.prefix}ses_{device_id}_{ep_idx:02d}_{att_idx:02d}"

                # Session rotation within episode
                if self.rng.random() < float(self.rng.uniform(scenario.session_rotation[0], scenario.session_rotation[1])):
                    session_id = f"{self.prefix}ses_{device_id}_{ep_idx:02d}_{att_idx:02d}_{int(self.rng.integers(1000, 9999))}"
                
                # IP rotation
                if scenario.name != "cgnat_mobile_ip_storm" and self.rng.random() < float(self.rng.uniform(scenario.ip_rotation[0], scenario.ip_rotation[1])):
                    ip_addr = self._draw_ip(episode_customer, scenario.ip_pool)

                # Card selection
                if scenario.card_diversity_mode == "high_rotation":
                    card = new_instrument(
                        self.rng,
                        self.instrument_config,
                        float(self.rng.uniform(scenario.method_validity[0], scenario.method_validity[1])),
                    )
                elif scenario.card_diversity_mode == "single_card":
                    card = instruments[0]
                elif scenario.card_diversity_mode == "wallet_cycle":
                    card = instruments[min(att_idx, len(instruments) - 1)]
                else:
                    if not instruments or self.rng.random() > float(self.rng.uniform(scenario.instrument_reuse[0], scenario.instrument_reuse[1])):
                        card = new_instrument(
                            self.rng,
                            self.instrument_config,
                            float(self.rng.uniform(scenario.method_validity[0], scenario.method_validity[1])),
                        )
                        instruments.append(card)
                    else:
                        card = self.rng.choice(instruments)

                last_card = card

                # Amount
                amount_style = self.rng.choice(
                    list(scenario.amount_style_weights.keys()),
                    p=list(scenario.amount_style_weights.values()),
                )
                if amount_style == "low":
                    amount = float(surface.get("amount", round(float(self.rng.uniform(1.0, 49.0)), 2)))
                elif amount_style == "repeat":
                    amount = repeated_amount
                else:
                    amount = float(surface.get("amount", merchant.draw_amount(self.rng)))

                req_id = f"{self.prefix}req_{self._next('request'):07d}"
                is_campaign = merchant.in_campaign(current_time) or scenario.prefers_campaign

                # Authorization Request (no outcome or card fields at request time)
                events.append(
                    blank_event(
                        "authorization_request",
                        current_time,
                        f"{self.prefix}evt_{self._next('event'):08d}",
                        request_id=req_id,
                        merchant_id=merchant.merchant_id,
                        customer_id=None if is_guest else episode_customer.customer_id,
                        device_id=device_id,
                        session_id=session_id,
                        ip_fingerprint=ip_addr,
                        amount=amount,
                        currency="INR",
                        campaign_active=is_campaign,
                    )
                )

                # Determine outcome
                instability = float(self.rng.uniform(
                    scenario.network_instability[0], scenario.network_instability[1]
                ))
                approved, cause = resolve_attempt(self.rng, merchant, card, instability)
                if approved:
                    result, reason = "approved", None
                else:
                    result = "declined"
                    reason = failure_reason(self.rng, card, str(cause))
                if cause == "instrument":
                    card.declined_before = True

                # Outcome event (2 seconds later)
                outcome_time = current_time + timedelta(seconds=int(self.rng.integers(1, 4)))
                events.append(
                    blank_event(
                        "authorization_outcome",
                        outcome_time,
                        f"{self.prefix}evt_{self._next('event'):08d}",
                        request_id=req_id,
                        device_id=device_id,
                        session_id=session_id,
                        authorization_result=result,
                        failure_reason=reason,
                        payment_method="card",
                        card_last4=card.last4,
                        card_network=card.network,
                        card_type=card.card_type,
                        card_issuer=card.issuer,
                        international=card.international,
                    )
                )

                # Checkout completion if approved
                if result == "approved" and self.rng.random() < float(self.rng.uniform(scenario.checkout_completion[0], scenario.checkout_completion[1])):
                    checkout_time = outcome_time + timedelta(seconds=int(self.rng.integers(5, 20)))
                    events.append(
                        blank_event(
                            "checkout_completion",
                            checkout_time,
                            f"{self.prefix}evt_{self._next('event'):08d}",
                            request_id=req_id,
                            device_id=device_id,
                            session_id=session_id,
                        )
                    )
                    # Stop attempts on success unless continue_after_success
                    if not surface and self.rng.random() > float(self.rng.uniform(scenario.continue_after_success[0], scenario.continue_after_success[1])):
                        break

                # Advance gap
                gap_sec = float(surface.get("gap_seconds", lognormal_gap(
                    self.rng,
                    float(self.rng.uniform(scenario.gap_seconds[0], scenario.gap_seconds[1])),
                    float(self.rng.uniform(scenario.gap_spread[0], scenario.gap_spread[1])),
                )))
                current_time = outcome_time + timedelta(seconds=gap_sec)

            # Advance episode gap
            ep_gap_days = float(self.rng.uniform(scenario.episode_gap_days[0], scenario.episode_gap_days[1]))
            current_time = current_time + timedelta(days=ep_gap_days)

        labels = [
            {
                "device_id": dev,
                "actor_id": actor_id,
                "leakage_group_id": (
                    f"{self.prefix}pair_{cf_pair_id}" if cf_pair_id else actor_id
                ),
                "customer_id": None if is_guest else primary_customer.customer_id,
                "merchant_id": merchant.merchant_id,
                "merchant_kind": merchant.kind,
                "population": scenario.population,
                "scenario": scenario.name,
                "label": scenario.label,
                "split": self.split_name,
                "counterfactual_pair_id": cf_pair_id,
                "counterfactual_role": cf_role,
            }
            for dev in sorted(used_devices)
        ]
        return events, labels

    def generate(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        target_devices = int(self.split["devices"])
        attack_fraction = float(self.split["benchmark_attack_device_fraction"])
        attack_device_target = int(round(target_devices * attack_fraction))
        legit_device_target = target_devices - attack_device_target

        events: list[dict] = []
        labels: list[dict] = []
        counts = {"attack": 0, "legitimate": 0}
        scenario_counts: dict[str, int] = {}

        # 1. First satisfy Critical Scenario Minimums
        crit_targets = self.config.get("critical_family_targets", {})
        split_ratio = target_devices / 12000.0  # proportional share
        for sc_name in CRITICAL_SCENARIOS:
            sc = self.scenarios[sc_name]
            base_min = crit_targets.get(sc_name, 280)
            sc_target = max(20, int(round(base_min * split_ratio)))
            while scenario_counts.get(sc_name, 0) < sc_target:
                actor_events, actor_labels = self._generate_actor(sc)
                if not actor_labels:
                    continue
                counts[sc.population] += len(actor_labels)
                scenario_counts[sc_name] = scenario_counts.get(sc_name, 0) + len(actor_labels)
                events.extend(actor_events)
                labels.extend(actor_labels)

        # 2. In validation, generate the 20 predeclared counterfactual designs.
        # Shared nuisance parameters are drawn once per pair and supplied to
        # both twins. Pair membership remains evaluation metadata only.
        if self.split_name == "validation":
            cf_designs = [
                ("fast_burst_v4", "network_retry_storm_hard", 6, 1, 10.0, 499.0),
                ("patient_tester_v4", "subscription_dunning_hard", 4, 1, 86400.0, 599.0),
                ("fast_burst_v4", "normal_returning_customer", 8, 1, 37.5, 20.0),
                ("cross_device_weak_guest", "shared_household_device", 4, 4, 1800.0, 1200.0),
                ("fast_burst_v4", "cvv_and_expiry_mistakes", 5, 1, 45.0, 799.0),
                ("sparse_multiday_v4", "dormant_account_spike", 5, 1, 172800.0, 1200.0),
                ("session_churn_v4", "session_recreation_flaky_net", 6, 1, 100.0, 850.0),
                ("success_camouflage_v4", "normal_returning_customer", 5, 1, 180.0, 1499.0),
                ("fast_burst_v4", "network_retry_storm_hard", 8, 1, 4.0, 1899.0),
                ("merchant_normal_amount_attack_v4", "genuine_wallet_cycling", 3, 1, 200.0, 45000.0),
                ("burst_pause_burst_v4", "session_recreation_flaky_net", 7, 1, 90.0, 999.0),
                ("distributed_bot_campaign", "cgnat_mobile_ip_storm", 12, 12, 15.0, 199.0),
                ("cross_device_partial", "shared_household_device", 4, 1, 180.0, 1499.0),
                ("fast_burst_v4", "genuine_wallet_cycling", 5, 1, 60.0, 100.0),
                ("merchant_normal_amount_attack_v4", "persistent_card_problem_hard", 5, 1, 90.0, 2500.0),
                ("session_churn_v4", "session_recreation_flaky_net", 4, 1, 150.0, 499.0),
                ("fast_burst_v4", "cvv_and_expiry_mistakes", 6, 1, 60.0, 799.0),
                ("ultra_patient_v4", "subscription_dunning_hard", 3, 1, 604800.0, 599.0),
                ("warm_up_then_attack_v4", "normal_returning_customer", 7, 1, 300.0, 1499.0),
                ("mixed_campaign_v4", "shared_household_device", 6, 3, 120.0, 1800.0),
            ]
            for pair_idx, design in enumerate(cf_designs, start=1):
                pair_id = f"CP-{pair_idx:02d}"
                att_sc_name, leg_sc_name, attempts, devices, gap_seconds, amount = design
                att_sc = self.scenarios[att_sc_name]
                leg_sc = self.scenarios[leg_sc_name]
                matched_merchant = self._pick_merchant(att_sc)
                shared_surface = {
                    "attempts": attempts,
                    "devices": devices,
                    "episodes": 1,
                    "gap_seconds": gap_seconds,
                    "amount": amount,
                    "start_time": self.window_start + timedelta(days=5 + pair_idx * 2),
                }

                # Generate attack twin
                att_evs, att_labs = self._generate_actor(
                    att_sc, force_merchant=matched_merchant, cf_pair_id=pair_id,
                    cf_role="attack", shared_surface=shared_surface,
                )
                counts["attack"] += len(att_labs)
                scenario_counts[att_sc_name] = scenario_counts.get(att_sc_name, 0) + len(att_labs)
                events.extend(att_evs)
                labels.extend(att_labs)

                # Generate legitimate twin
                leg_evs, leg_labs = self._generate_actor(
                    leg_sc, force_merchant=matched_merchant, cf_pair_id=pair_id,
                    cf_role="legitimate_twin", shared_surface=shared_surface,
                )
                counts["legitimate"] += len(leg_labs)
                scenario_counts[leg_sc_name] = scenario_counts.get(leg_sc_name, 0) + len(leg_labs)
                events.extend(leg_evs)
                labels.extend(leg_labs)

        # 3. Fill remaining quota proportionally according to scenario weights
        attack_pool = [s for s in self.scenarios.values() if s.population == "attack"]
        legit_pool = [s for s in self.scenarios.values() if s.population == "legitimate"]
        # Scenario weights describe desired DEVICE coverage. Sampling actors
        # directly would over-represent 20-device CGNAT and 50-device campaign
        # actors, so divide by expected devices emitted per actor.
        att_weights = np.array([
            s.weight / ((s.devices[0] + s.devices[1]) / 2.0) for s in attack_pool
        ], dtype=float)
        leg_weights = np.array([
            s.weight / ((s.devices[0] + s.devices[1]) / 2.0) for s in legit_pool
        ], dtype=float)

        while counts["attack"] < attack_device_target or counts["legitimate"] < legit_device_target:
            if counts["attack"] >= attack_device_target:
                sc = legit_pool[int(self.rng.choice(len(legit_pool), p=leg_weights / leg_weights.sum()))]
            elif counts["legitimate"] >= legit_device_target:
                sc = attack_pool[int(self.rng.choice(len(attack_pool), p=att_weights / att_weights.sum()))]
            else:
                if self.rng.random() < attack_fraction:
                    sc = attack_pool[int(self.rng.choice(len(attack_pool), p=att_weights / att_weights.sum()))]
                else:
                    sc = legit_pool[int(self.rng.choice(len(legit_pool), p=leg_weights / leg_weights.sum()))]

            actor_events, actor_labels = self._generate_actor(sc)
            if not actor_labels:
                continue
            target_for_population = (
                attack_device_target if sc.population == "attack" else legit_device_target
            )
            remaining = target_for_population - counts[sc.population]
            if len(actor_labels) > remaining:
                # Keep the correlated actor indivisible. Retry with another
                # deterministic draw instead of trimming devices from a group.
                continue
            counts[sc.population] += len(actor_labels)
            scenario_counts[sc.name] = scenario_counts.get(sc.name, 0) + len(actor_labels)
            events.extend(actor_events)
            labels.extend(actor_labels)

        frame = pd.DataFrame(events, columns=list(EVENT_COLUMNS))
        frame = frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        frame["split"] = self.split_name
        label_frame = pd.DataFrame(labels, columns=list(LABEL_COLUMNS))
        return frame, label_frame


def generate_dataset_v4(config: dict) -> dict:
    merchants = build_merchants_v4(config)
    splits = config["splits"]

    train_start = datetime.fromisoformat(str(splits["train"]["start"]))
    train_gen = GeneratorV4(config, "train", splits["train"], merchants, train_start)
    train_raw, train_labels = train_gen.generate()

    val_start = datetime.fromisoformat(str(splits["validation"]["start"]))
    val_gen = GeneratorV4(config, "validation", splits["validation"], merchants, val_start)
    val_raw, val_labels = val_gen.generate()

    raw_events = pd.concat([train_raw, val_raw], ignore_index=True)
    labels = pd.concat([train_labels, val_labels], ignore_index=True)

    # Re-sort events globally, set monotonic event_sequence, and format timestamps
    raw_events = raw_events.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    raw_events["event_sequence"] = range(1, len(raw_events) + 1)
    raw_events["timestamp"] = raw_events["timestamp"].map(
        lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value)
    )

    return {
        "raw_events": raw_events,
        "labels": labels,
        "merchants": merchants,
        "train_raw": train_raw,
        "train_labels": train_labels,
        "val_raw": val_raw,
        "val_labels": val_labels,
    }


def build_manifest_v4(config: dict, bundle: dict) -> dict:
    raw = bundle["raw_events"]
    labels = bundle["labels"]
    auth_requests = raw.loc[raw.event_type.eq("authorization_request")]

    device_scenario = labels.groupby("scenario")["device_id"].nunique().to_dict()
    device_population = labels.groupby("population")["device_id"].nunique().to_dict()
    cf_pairs = labels.dropna(subset=["counterfactual_pair_id"])["counterfactual_pair_id"].nunique()

    return {
        "dataset_name": config["dataset_name"],
        "generator_version": config["generator_version"],
        "spec_version": config["spec_version"],
        "total_events": len(raw),
        "total_authorization_requests": len(auth_requests),
        "total_devices": int(labels["device_id"].nunique()),
        "devices_by_population": device_population,
        "devices_by_scenario": device_scenario,
        "counterfactual_pairs_count": int(cf_pairs),
        "splits": {
            split: {
                "devices": int(labels.loc[labels.split.eq(split), "device_id"].nunique()),
                "requests": int(raw.loc[raw.split.eq(split) & raw.event_type.eq("authorization_request"), "request_id"].nunique()),
                "attack_devices": int(labels.loc[labels.split.eq(split) & labels.label.eq(1), "device_id"].nunique()),
                "legitimate_devices": int(labels.loc[labels.split.eq(split) & labels.label.eq(0), "device_id"].nunique()),
            }
            for split in labels["split"].unique()
        },
    }
