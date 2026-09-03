"""Independent generator for the frozen PBRSS-v1 stress specification.

This module deliberately knows nothing about models, policies, thresholds,
development metrics, or evaluation artifacts.  It emits lifecycle events and
device labels; causal feature replay is a separate pipeline responsibility.
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


def _token(seed: int, namespace: str, number: int) -> str:
    value = hashlib.sha256(f"{seed}:{namespace}:{number}".encode()).hexdigest()[:20]
    return f"pbs_{value}"


def build_merchants(config: dict) -> list[MerchantProfile]:
    spec = config["merchants"]
    if int(spec["count"]) != len(spec["archetypes"]) * int(spec["per_archetype"]):
        raise ValueError("merchant allocation must cover every archetype equally")
    merchants = []
    seed = int(config["seed"])
    for kind, values in sorted(spec["archetypes"].items()):
        for slot in range(int(spec["per_archetype"])):
            merchant_id = _token(seed, f"merchant-{kind}", slot)
            merchants.append(
                MerchantProfile(
                    merchant_id=merchant_id,
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
        if config.get("spec_version") != SPEC_VERSION:
            raise ValueError("unexpected PBRSS specification")
        if config.get("generator_version") != GENERATOR_VERSION:
            raise ValueError("unexpected PBRSS generator version")
        self.config = config
        self.seed = int(config["seed"])
        self.rng = np.random.default_rng(self.seed)
        self.merchants = build_merchants(config)
        self.start = datetime.fromisoformat(str(config["window"]["start"]))
        self.events: list[dict] = []
        self.labels: list[dict] = []
        self.counters = {
            "actor": 0,
            "device": 0,
            "request": 0,
            "event": 0,
            "customer": 0,
        }

    def _id(self, kind: str) -> str:
        self.counters[kind] += 1
        return _token(self.seed, kind, self.counters[kind])

    def _emit_attempt(
        self,
        *,
        actor: str,
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
        delay = float(
            np.clip(
                (self.rng.pareto(float(self.config["population"]["pareto_shape"])) + 1)
                * 1.5,
                *self.config["population"]["network_delay_seconds"],
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

    def _actor(
        self,
        merchant: MerchantProfile,
        population: str,
        scenario: str,
        *,
        device_count: int = 1,
        attempts: int = 4,
        start_at: datetime | None = None,
    ) -> None:
        actor = self._id("actor")
        guest_rate = float(
            self.rng.uniform(*self.config["population"]["guest_checkout_rate"])
        )
        shared_ip = f"100.64.{self.counters['actor'] % 250}.0/24"
        devices = [self._id("device") for _ in range(device_count)]
        primary_customer = (
            None if self.rng.random() < guest_rate else self._id("customer")
        )
        base = start_at or self.start + timedelta(
            days=float(self.rng.uniform(0, int(self.config["window"]["days"]) - 15))
        )
        instruments = [
            new_instrument(
                self.rng,
                {
                    "methods": ["card"],
                    "method_weights": [1],
                    "last4_pool": 10000,
                    "networks": ["visa", "mastercard", "rupay"],
                    "network_weights": [4, 4, 2],
                    "types": ["credit", "debit"],
                    "type_weights": [6, 4],
                    "issuers": 30,
                    "international_rate": 0.08,
                },
                0.65 if population == "attack" else 0.82,
            )
            for _ in range(max(attempts, 4))
        ]

        for device_index, device in enumerate(devices):
            current = base + timedelta(seconds=device_index * 2)
            customer = primary_customer
            session = self._id("event")
            for attempt in range(attempts):
                if scenario == "stealth_low_amount_drip":
                    amount = self.rng.uniform(1, 5)
                    gap = self.rng.uniform(18, 36) * 3600
                    card = instruments[attempt % len(instruments)]
                elif scenario == "charity_micro_donation_spike":
                    amount = self.rng.uniform(50, 100)
                    gap = self.rng.uniform(1.5, 3.0)
                    card = instruments[0]
                    customer = None
                elif scenario == "b2b_multi_corporate_card":
                    amount, gap = 120000.0, self.rng.uniform(45, 240)
                    card = instruments[attempt % 4]
                else:
                    amount = (
                        self.rng.uniform(1, 5)
                        if self.rng.random() < 0.1
                        else merchant.draw_amount(self.rng)
                    )
                    if attempt < 2:
                        gap = self.rng.uniform(1.5, 3.0)
                    elif attempt == 2 and self.rng.random() < 0.2:
                        gap = (
                            self.rng.uniform(
                                *self.config["population"]["long_retry_days"]
                            )
                            * 86400
                        )
                    else:
                        pause = self.rng.pareto(2.2) + 1.0
                        gap = np.clip(pause, 1.0, 48.0) * 3600
                    card = (
                        instruments[attempt % len(instruments)]
                        if population == "attack"
                        else instruments[0]
                    )
                approved = bool(
                    self.rng.random() < (0.35 if population == "attack" else 0.72)
                )
                outcome = self._emit_attempt(
                    actor=actor,
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
                if scenario == "hybrid_credential_stuffing_probe" and not approved:
                    customer = self._id("customer")
                current = outcome + timedelta(seconds=float(gap))
            self.labels.append(
                {
                    "device_id": device,
                    "actor_id": actor,
                    "leakage_group_id": actor,
                    "customer_id": customer,
                    "merchant_id": merchant.merchant_id,
                    "merchant_kind": merchant.kind,
                    "population": population,
                    "scenario": scenario,
                    "label": int(population == "attack"),
                    "split": self.config["split"],
                    "counterfactual_pair_id": None,
                    "counterfactual_role": None,
                }
            )

    def generate(self) -> dict[str, pd.DataFrame | list[MerchantProfile]]:
        target = int(self.config["population"]["devices"])
        attack_target = round(
            target * float(self.config["population"]["attack_device_fraction"])
        )
        # Coverage is deliberately symmetric at every new merchant.
        for index, merchant in enumerate(self.merchants):
            attack_scenario = (
                "stealth_low_amount_drip"
                if index == 0
                else (
                    "hybrid_credential_stuffing_probe"
                    if index == 1
                    else "mixed_card_probe"
                )
            )
            legitimate_scenario = (
                "charity_micro_donation_spike"
                if merchant.kind == "donation_charity"
                else (
                    "b2b_multi_corporate_card"
                    if merchant.kind == "b2b_wholesale"
                    else "ordinary_checkout"
                )
            )
            self._actor(
                merchant, "attack", attack_scenario, attempts=7 if index == 0 else 4
            )
            self._actor(merchant, "legitimate", legitimate_scenario, attempts=4)
        # The canonical-sized suite includes the predeclared viral charity
        # cohort.  Actors are capped at the frozen 80-device CGNAT density.
        if target >= 1000:
            charity = next(
                merchant
                for merchant in self.merchants
                if merchant.kind == "donation_charity"
            )
            remaining_charity = min(500, target // 8)
            charity_start = self.start + timedelta(days=60)
            while remaining_charity:
                cohort = min(
                    int(self.config["population"]["cgnat_devices_per_subnet"]),
                    remaining_charity,
                )
                self._actor(
                    charity,
                    "legitimate",
                    "charity_micro_donation_spike",
                    device_count=cohort,
                    attempts=2,
                    start_at=charity_start,
                )
                remaining_charity -= cohort
            # Match the maximum shared-network density in an attack family so
            # cohort size and IP fanout do not encode the class label.
            self._actor(
                self.merchants[0],
                "attack",
                "mixed_card_probe",
                device_count=int(self.config["population"]["cgnat_devices_per_subnet"]),
                attempts=2,
                start_at=self.start + timedelta(days=75),
            )
        while len(self.labels) < target:
            attacks = sum(row["label"] for row in self.labels)
            population = "attack" if attacks < attack_target else "legitimate"
            merchant = self.merchants[len(self.labels) % len(self.merchants)]
            scenario = (
                "mixed_card_probe" if population == "attack" else "ordinary_checkout"
            )
            self._actor(
                merchant, population, scenario, attempts=int(self.rng.integers(3, 6))
            )
        raw = pd.DataFrame(self.events, columns=EVENT_COLUMNS)
        raw = raw.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        raw["event_sequence"] = np.arange(1, len(raw) + 1)
        raw["timestamp"] = raw["timestamp"].map(lambda value: value.isoformat())
        raw["split"] = self.config["split"]
        labels = pd.DataFrame(self.labels, columns=LABEL_COLUMNS)
        return {"raw_events": raw, "labels": labels, "merchants": self.merchants}


def build_manifest(config: dict, bundle: dict) -> dict:
    raw, labels = bundle["raw_events"], bundle["labels"]
    return {
        "dataset_name": config["dataset_name"],
        "spec_version": SPEC_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": int(config["seed"]),
        "events": int(len(raw)),
        "authorization_requests": int(raw.event_type.eq("authorization_request").sum()),
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
