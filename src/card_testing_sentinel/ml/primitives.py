"""Neutral synthetic-generation primitives.

Shared by the development generator and the blind generator. Everything here
is mechanics -- what a payment instrument looks like, how a gateway resolves
an attempt, what columns an event row has. None of it encodes a scenario
table, a label, a model, a policy threshold or any evaluation result, which
is what lets the blind generator reuse it while staying independent of the
frozen system it is meant to test.

Nothing in this module may ever import `modeling`, `policy`, or the training
and evaluation modules. An import-graph test enforces that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from card_testing_sentinel.ml.merchants import MerchantProfile

#: Emitted event columns, in a stable order.
EVENT_COLUMNS = (
    "event_id",
    "event_sequence",
    "timestamp",
    "event_type",
    "request_id",
    "merchant_id",
    "customer_id",
    "device_id",
    "session_id",
    "ip_fingerprint",
    "amount",
    "currency",
    "campaign_active",
    "authorization_result",
    "failure_reason",
    "payment_method",
    "card_last4",
    "card_network",
    "card_type",
    "card_issuer",
    "international",
)

#: Chance an unusable instrument is approved anyway. Gateway constants,
#: identical for every actor and population.
UNUSABLE_SUCCESS = 0.05
#: A card that already declined for its own reason rarely starts working.
REPEAT_DECLINE = 0.80

#: Failure reasons split by cause, so the reason reflects what went wrong
#: rather than who the actor is.
INSTRUMENT_REASONS = ("do_not_honor", "card_declined", "insufficient_funds")
NETWORK_REASONS = ("generic_decline", "authentication_failed")


@dataclass
class Instrument:
    """A payment instrument as the *merchant* eventually learns about it:
    only the coarse metadata a verified Razorpay outcome reports."""

    usable: bool
    method: str
    last4: str
    network: str
    card_type: str
    issuer: str
    international: bool
    declined_before: bool = False


def weighted_choice(rng: np.random.Generator, options, weights) -> str:
    probabilities = np.asarray(weights, dtype=float)
    return str(rng.choice(options, p=probabilities / probabilities.sum()))


def new_instrument(
    rng: np.random.Generator, spec: dict, method_validity: float
) -> Instrument:
    """A small last4 space, so two unrelated instruments collide sometimes:
    last4 is a weak hint, never an identity."""
    return Instrument(
        usable=bool(rng.random() < method_validity),
        method=weighted_choice(rng, spec["methods"], spec["method_weights"]),
        last4=f"{int(rng.integers(0, int(spec['last4_pool']))) % 10000:04d}",
        network=weighted_choice(rng, spec["networks"], spec["network_weights"]),
        card_type=weighted_choice(rng, spec["types"], spec["type_weights"]),
        issuer=f"issuer_{int(rng.integers(1, int(spec['issuers']) + 1)):02d}",
        international=bool(rng.random() < float(spec["international_rate"])),
    )


def resolve_attempt(
    rng: np.random.Generator,
    merchant: MerchantProfile,
    instrument: Instrument,
    network_instability: float,
) -> tuple[bool, str | None]:
    """Resolve one payment, and say *why* it failed.

    The cause matters: a network/gateway failure says nothing about the card,
    so it must not poison an otherwise good instrument. Only an
    instrument-side decline makes later attempts on the same instrument more
    likely to fail.
    """
    if not instrument.usable and rng.random() >= UNUSABLE_SUCCESS:
        return False, "instrument"
    if instrument.declined_before and rng.random() < REPEAT_DECLINE:
        return False, "instrument"
    if rng.random() < network_instability:
        return False, "network"
    if rng.random() < merchant.base_success_rate:
        return True, None
    return False, "network"


def failure_reason(rng: np.random.Generator, instrument: Instrument, cause: str) -> str:
    if cause == "instrument" and instrument.international and rng.random() < 0.3:
        return "international_blocked"
    pool = INSTRUMENT_REASONS if cause == "instrument" else NETWORK_REASONS
    return str(rng.choice(pool))


def lognormal_gap(
    rng: np.random.Generator, base_seconds: float, spread: float
) -> float:
    """Lognormal around a base cadence, so every family has a long tail that
    reaches into its neighbours' ranges."""
    return float(max(1.0, rng.lognormal(np.log(max(base_seconds, 1.0)), spread)))


def choose_amount(
    rng: np.random.Generator,
    merchant: MerchantProfile,
    weights: dict[str, float],
    previous: float | None,
    multiplier: float = 1.0,
) -> float:
    """Draw an amount by style.

    `low` covers genuine micro-payments (tips, top-ups, verification charges)
    as well as testing; `high` covers genuine big-ticket purchases. Neither
    style belongs to a population -- both appear in legitimate and attack
    families, which is what stops amount alone from carrying the label.
    """
    styles = sorted(weights)
    style = weighted_choice(rng, styles, [weights[name] for name in styles])
    if style == "repeat" and previous is not None:
        return previous
    if style == "low":
        return round(float(rng.uniform(1.0, 9.0)), 2)
    if style == "high":
        return merchant.draw_amount(rng, multiplier * float(rng.uniform(2.5, 6.0)))
    if style == "varied":
        return merchant.draw_amount(rng, multiplier * float(rng.uniform(0.2, 3.0)))
    return merchant.draw_amount(rng, multiplier)


def blank_event(event_type: str, timestamp: datetime, event_id: str, **fields) -> dict:
    row = dict.fromkeys(EVENT_COLUMNS)
    row["event_id"] = event_id
    row["event_type"] = event_type
    row["timestamp"] = timestamp
    row.update(fields)
    return row
