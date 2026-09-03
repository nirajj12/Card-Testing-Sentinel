"""Config-driven synthetic generator for the frozen PBRSS-v1 design.

This module emits lifecycle events and device labels only. It has no access to
trained artifacts, scores, thresholds, evaluation results, or application
decisions. Causal feature replay remains a separate pipeline responsibility.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from card_testing_sentinel.ml.merchants import MerchantProfile
from card_testing_sentinel.ml.primitives import (
    EVENT_COLUMNS,
    blank_event,
    new_instrument,
)

SPEC_VERSION = "pbrss-v1-frozen-spec"
GENERATOR_VERSION = "pbrss-v1-generator-1"
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
INSTRUMENT_SPEC = {
    "methods": ["card"],
    "method_weights": [1],
    "last4_pool": 10000,
    "networks": ["visa", "mastercard", "rupay"],
    "network_weights": [4, 4, 2],
    "types": ["credit", "debit"],
    "type_weights": [6, 4],
    "issuers": 30,
    "international_rate": 0.08,
}


def _token(seed: int, namespace: str, number: int) -> str:
    digest = hashlib.sha256(f"{seed}:{namespace}:{number}".encode()).hexdigest()
    return f"pbs_{digest[:20]}"


def scenario_specs(config: dict) -> dict[str, dict]:
    return {
        **config["scenarios"]["held_out"],
        **config["scenarios"]["background"],
    }


def validate_config(config: dict) -> None:
    if config.get("spec_version") != SPEC_VERSION:
        raise ValueError("unexpected PBRSS specification")
    if config.get("generator_version") != GENERATOR_VERSION:
        raise ValueError("unexpected PBRSS generator version")
    target = int(config["population"]["devices"])
    expected_attack = round(
        target * float(config["population"]["attack_device_fraction"])
    )
    scenarios = scenario_specs(config)
    totals = {"attack": 0, "legitimate": 0}
    for name, spec in scenarios.items():
        population = str(spec["population"])
        if population not in totals:
            raise ValueError(f"unknown population for {name}")
        quota = int(spec["device_target"])
        if quota < 1:
            raise ValueError(f"scenario quota must be positive: {name}")
        totals[population] += quota
        available = config["outcome_profiles"][population]
        unknown = set(spec["outcome_profiles"]) - set(available)
        if unknown:
            raise ValueError(f"unknown outcome profiles for {name}: {sorted(unknown)}")
    if sum(totals.values()) != target:
        raise ValueError("scenario device quotas do not equal total device target")
    if totals["attack"] != expected_attack:
        raise ValueError("scenario quotas do not equal the attack-device target")
    hybrid = scenarios["hybrid_credential_stuffing_probe"]
    if not hybrid.get("synthetic_defence_only"):
        raise ValueError("hybrid scenario must remain synthetic defensive telemetry")
    if int(config["merchants"]["count"]) != 16:
        raise ValueError("PBRSS-v1 requires exactly 16 merchants")


def build_merchants(config: dict) -> list[MerchantProfile]:
    merchant_spec = config["merchants"]
    expected = len(merchant_spec["archetypes"]) * int(merchant_spec["per_archetype"])
    if int(merchant_spec["count"]) != expected:
        raise ValueError("merchant allocation must cover every archetype equally")
    merchants = []
    seed = int(config["seed"])
    for kind, values in sorted(merchant_spec["archetypes"].items()):
        for slot in range(int(merchant_spec["per_archetype"])):
            merchants.append(
                MerchantProfile(
                    merchant_id=_token(seed, f"merchant-{kind}", slot),
                    kind=kind,
                    typical_amount=float(values["typical_amount"]),
                    amount_spread=float(values["amount_spread"]),
                    base_success_rate=float(values["success_rate"]),
                    campaign_share=0.0,
                    returning_customer_rate=0.5,
                    shared_ip_pressure=0.2,
                    origin=str(values.get("origin", "known")),
                )
            )
    return merchants


class PBRSSV1Generator:
    def __init__(self, config: dict):
        validate_config(config)
        self.config = config
        self.seed = int(config["seed"])
        self.rng = np.random.default_rng(self.seed)
        self.merchants = build_merchants(config)
        self.start = datetime.fromisoformat(str(config["window"]["start"]))
        self.events: list[dict] = []
        self.labels: list[dict] = []
        self.counters = dict.fromkeys(
            ("actor", "device", "request", "event", "customer", "session"), 0
        )
        self.merchant_cursor = {"attack": 0, "legitimate": 0}

    def _id(self, kind: str) -> str:
        self.counters[kind] += 1
        return _token(self.seed, kind, self.counters[kind])

    def _outcome_probability(self, population: str, scenario: dict) -> float:
        profiles = self.config["outcome_profiles"][population]
        allowed = list(scenario["outcome_profiles"])
        weights = np.asarray([float(profiles[name]["weight"]) for name in allowed])
        selected = str(self.rng.choice(allowed, p=weights / weights.sum()))
        return float(self.rng.uniform(*profiles[selected]["approval_probability"]))

    def _emit_attempt(
        self,
        *,
        device: str,
        merchant: MerchantProfile,
        customer: str | None,
        moment: datetime,
        amount: float,
        card,
        approved: bool,
        session: str,
        ip_address: str,
    ) -> datetime:
        request = self._id("request")
        common = dict(request_id=request, device_id=device, session_id=session)
        self.events.append(
            blank_event(
                "authorization_request",
                moment,
                self._id("event"),
                **common,
                merchant_id=merchant.merchant_id,
                customer_id=customer,
                ip_fingerprint=ip_address,
                amount=round(float(amount), 2),
                currency="INR",
                campaign_active=False,
            )
        )
        population = self.config["population"]
        delay = float(
            np.clip(
                (self.rng.pareto(float(population["pareto_shape"])) + 1) * 1.5,
                *population["network_delay_seconds"],
            )
        )
        outcome = moment + timedelta(seconds=delay)
        self.events.append(
            blank_event(
                "authorization_outcome",
                outcome,
                self._id("event"),
                **common,
                authorization_result="approved" if approved else "declined",
                failure_reason=None if approved else "do_not_honor",
                payment_method="card",
                card_last4=card.last4,
                card_network=card.network,
                card_type=card.card_type,
                card_issuer=card.issuer,
                international=card.international,
            )
        )
        if approved:
            self.events.append(
                blank_event(
                    "checkout_completion",
                    outcome + timedelta(seconds=8),
                    self._id("event"),
                    **common,
                )
            )
        return outcome

    def _generic_gap(self, attempt: int) -> float:
        population = self.config["population"]
        if attempt < 2:
            return float(self.rng.uniform(*population["short_retry_seconds"]))
        if attempt == 2 and self.rng.random() < 0.2:
            return float(self.rng.uniform(*population["long_retry_days"]) * 86400)
        low, high = population["attack_pause_hours"]
        pause = float(self.rng.pareto(float(population["pareto_shape"])) + low)
        return float(np.clip(pause, low, high) * 3600)

    def _actor(
        self,
        merchant: MerchantProfile,
        scenario_name: str,
        scenario: dict,
        *,
        device_count: int = 1,
        start_at: datetime | None = None,
    ) -> None:
        population = str(scenario["population"])
        actor = self._id("actor")
        shared_ip = f"100.64.{self.counters['actor'] % 250}.0/24"
        guest_bounds = scenario.get(
            "guest_rate", self.config["population"]["guest_checkout_rate"]
        )
        approval_probability = self._outcome_probability(population, scenario)
        base = start_at or self.start + timedelta(
            days=float(self.rng.uniform(0, int(self.config["window"]["days"]) - 15))
        )
        for device_index in range(device_count):
            device = self._id("device")
            customer = (
                None
                if self.rng.random() < float(self.rng.uniform(*guest_bounds))
                else self._id("customer")
            )
            session = self._id("session")
            attempts = int(
                self.rng.integers(
                    int(scenario["attempts"][0]), int(scenario["attempts"][1]) + 1
                )
            )
            instruments = [
                new_instrument(self.rng, INSTRUMENT_SPEC, 0.75)
                for _ in range(max(attempts, int(scenario.get("corporate_cards", 1))))
            ]
            if scenario_name == "charity_micro_donation_spike":
                safe_window = max(float(scenario["burst_hours"]) * 3600 - 600, 0)
                current = base + timedelta(
                    seconds=float(self.rng.uniform(0, safe_window))
                )
            else:
                current = base + timedelta(seconds=device_index * 2)
            elapsed_hours = 0.0
            last_customer = customer
            for attempt in range(attempts):
                request_moment = current
                if scenario_name == "stealth_low_amount_drip":
                    amount = self.rng.uniform(*scenario["amount"])
                    remaining = attempts - attempt - 2
                    minimum = float(scenario["gap_hours"][0])
                    budget = float(scenario["duration_days"]) * 24 - elapsed_hours
                    upper = min(
                        float(scenario["gap_hours"][1]),
                        budget - max(0, remaining) * minimum,
                    )
                    gap = float(self.rng.uniform(minimum, max(minimum, upper))) * 3600
                    card = instruments[attempt]
                elif scenario_name == "charity_micro_donation_spike":
                    amount = self.rng.uniform(*scenario["amount"])
                    gap = float(
                        self.rng.uniform(
                            *self.config["population"]["short_retry_seconds"]
                        )
                    )
                    card, customer = instruments[0], None
                elif scenario_name == "b2b_multi_corporate_card":
                    amount = float(scenario["amount"])
                    gap = float(self.rng.uniform(*scenario["retry_gap_seconds"]))
                    card = instruments[attempt % int(scenario["corporate_cards"])]
                else:
                    amount = (
                        self.rng.uniform(*scenario["low_amount"])
                        if self.rng.random() < float(scenario["low_amount_probability"])
                        else merchant.draw_amount(self.rng)
                    )
                    gap = self._generic_gap(attempt)
                    card = (
                        instruments[attempt]
                        if population == "attack"
                        else instruments[0]
                    )

                approved = bool(self.rng.random() < approval_probability)
                if (
                    scenario_name == "charity_micro_donation_spike"
                    and attempt == 0
                    and bool(scenario["required_initial_failure"])
                ):
                    approved = False
                if scenario_name == "b2b_multi_corporate_card":
                    if attempt < int(scenario["required_initial_failures"]):
                        approved = False
                    elif attempt == attempts - 1 and bool(
                        scenario["required_final_success"]
                    ):
                        approved = True
                outcome = self._emit_attempt(
                    device=device,
                    merchant=merchant,
                    customer=customer,
                    moment=current,
                    amount=amount,
                    card=card,
                    approved=approved,
                    session=session,
                    ip_address=shared_ip,
                )
                if (
                    scenario_name == "hybrid_credential_stuffing_probe"
                    and not approved
                    and bool(scenario["identity_switch_after_decline"])
                ):
                    customer = self._id("customer")
                last_customer = customer
                current = (
                    request_moment + timedelta(seconds=gap)
                    if scenario_name == "stealth_low_amount_drip"
                    else outcome + timedelta(seconds=gap)
                )
                elapsed_hours += gap / 3600
            self.labels.append(
                {
                    "device_id": device,
                    "actor_id": actor,
                    "leakage_group_id": actor,
                    "customer_id": last_customer,
                    "merchant_id": merchant.merchant_id,
                    "merchant_kind": merchant.kind,
                    "population": population,
                    "scenario": scenario_name,
                    "label": int(population == "attack"),
                    "split": self.config["split"],
                    "counterfactual_pair_id": None,
                    "counterfactual_role": None,
                }
            )

    def _eligible_merchants(self, scenario_name: str) -> list[MerchantProfile]:
        if scenario_name == "charity_micro_donation_spike":
            return [m for m in self.merchants if m.kind == "donation_charity"]
        if scenario_name == "b2b_multi_corporate_card":
            return [m for m in self.merchants if m.kind == "b2b_wholesale"]
        return self.merchants

    def _generate_quota(self, scenario_name: str, scenario: dict) -> None:
        remaining = int(scenario["device_target"])
        merchants = self._eligible_merchants(scenario_name)
        population = str(scenario["population"])
        index = self.merchant_cursor[population] if len(merchants) == 16 else 0
        common_start = self.start + timedelta(days=60)
        while remaining:
            cohort = 1
            if scenario_name in {"charity_micro_donation_spike", "mixed_card_probe"}:
                cohort = min(
                    remaining,
                    int(self.config["population"]["cgnat_devices_per_subnet"]),
                )
            self._actor(
                merchants[index % len(merchants)],
                scenario_name,
                scenario,
                device_count=cohort,
                start_at=(
                    common_start
                    if scenario_name == "charity_micro_donation_spike"
                    else None
                ),
            )
            remaining -= cohort
            index += 1
        if len(merchants) == 16:
            self.merchant_cursor[population] = index % len(merchants)

    def generate(self) -> dict[str, pd.DataFrame | list[MerchantProfile]]:
        for scenario_name, scenario in scenario_specs(self.config).items():
            self._generate_quota(scenario_name, scenario)
        raw = pd.DataFrame(self.events, columns=EVENT_COLUMNS)
        raw = raw.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        raw["event_sequence"] = np.arange(1, len(raw) + 1)
        raw["timestamp"] = raw["timestamp"].map(lambda value: value.isoformat())
        raw["split"] = self.config["split"]
        labels = pd.DataFrame(self.labels, columns=LABEL_COLUMNS)
        bundle = {"raw_events": raw, "labels": labels, "merchants": self.merchants}
        validate_bundle(self.config, bundle)
        return bundle


def validate_bundle(config: dict, bundle: dict) -> None:
    raw, labels = bundle["raw_events"], bundle["labels"]
    target = int(config["population"]["devices"])
    attack_target = round(
        target * float(config["population"]["attack_device_fraction"])
    )
    counts = (
        labels.device_id.nunique(),
        labels.loc[labels.label.eq(1), "device_id"].nunique(),
        labels.loc[labels.label.eq(0), "device_id"].nunique(),
    )
    if counts != (target, attack_target, target - attack_target):
        raise ValueError("generated population counts differ from frozen allocation")
    if labels.merchant_id.nunique() != int(config["merchants"]["count"]):
        raise ValueError("generated merchant count differs from frozen allocation")
    actual = labels.groupby("scenario").device_id.nunique().to_dict()
    expected = {
        name: int(spec["device_target"])
        for name, spec in scenario_specs(config).items()
    }
    if actual != expected:
        raise ValueError("generated scenario quotas differ from frozen allocation")
    requests = int(raw.event_type.eq("authorization_request").sum())
    request_target = int(config["population"]["target_requests"])
    tolerance = float(config["population"]["request_target_tolerance_fraction"])
    if (
        not request_target * (1 - tolerance)
        <= requests
        <= request_target * (1 + tolerance)
    ):
        raise ValueError("authorization request count is outside frozen tolerance")
    if not labels.groupby("merchant_id").label.nunique().eq(2).all():
        raise ValueError("every merchant must contain both populations")


def build_manifest(config: dict, bundle: dict) -> dict:
    raw, labels = bundle["raw_events"], bundle["labels"]
    return {
        "dataset_name": config["dataset_name"],
        "spec_version": SPEC_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": int(config["seed"]),
        "events": int(len(raw)),
        "authorization_requests": int(raw.event_type.eq("authorization_request").sum()),
        "request_target": int(config["population"]["target_requests"]),
        "request_target_tolerance_fraction": float(
            config["population"]["request_target_tolerance_fraction"]
        ),
        "devices": int(labels.device_id.nunique()),
        "attack_devices": int(labels.loc[labels.label.eq(1), "device_id"].nunique()),
        "legitimate_devices": int(
            labels.loc[labels.label.eq(0), "device_id"].nunique()
        ),
        "merchants": int(labels.merchant_id.nunique()),
        "archetypes": sorted(labels.merchant_kind.unique().tolist()),
        "scenarios": labels.groupby("scenario")
        .device_id.nunique()
        .sort_index()
        .to_dict(),
        "contains_model_scores": False,
        "contains_policy_decisions": False,
        "evaluated": False,
        "consumed": False,
    }
