"""Persistent customers and covering merchant allocation for Dataset v3.

The defect this module exists to fix: Dataset V2 minted a fresh customer id
per actor (``cus_{actor_id}_{i}``), so no customer ever spanned two devices,
two merchants or two points in time. Every customer-scoped feature would have
been degenerate, and an ablation would have "proved" the idea worthless for
reasons belonging entirely to the generator.

A v3 customer is drawn once, joins the window once, and persists. Tenure and
history are NOT attributes -- they emerge from the episodes actually
generated after ``joined_at``. Nothing here stores a success count, a failure
count or any other quantity a feature could read directly.

This module is new. It never edits ``ml/merchants.py``, ``ml/scenarios.py``
or ``ml/primitives.py``, all of which are hashed inside the Blind v1.1 freeze
bundle -- it imports the neutral mechanics from them read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from card_testing_sentinel.ml.merchants import (
    MerchantProfile,
    make_merchant,
    resolve_calendar,
)


class DatasetV3Error(RuntimeError):
    """Raised when generation would violate Dataset v3's own rules."""


@dataclass(frozen=True)
class CustomerProfile:
    """A person, not a risk level.

    ``login_propensity`` is how likely this person is signed in at all; the
    per-episode decision also depends on what they are doing and where, so
    the same customer can check out as a guest at a flash sale and be logged
    in at their subscription service.
    """

    customer_id: str
    joined_at: datetime
    home_ips: tuple[str, ...]
    login_propensity: float
    on_shared_ip: bool

    def tenure_seconds(self, now: datetime) -> float:
        """Only ever used to place episodes -- never emitted as a feature."""
        return max((now - self.joined_at).total_seconds(), 0.0)


def build_customers(
    rng: np.random.Generator,
    config: dict,
    count: int,
    window_start: datetime,
    window_days: int,
    prefix: str,
) -> list[CustomerProfile]:
    """Draw a persistent customer population for one split.

    Customers join inside the first ``join_window_fraction`` of the window, so
    an early joiner accumulates real history before its later episodes while
    a late joiner genuinely has none.
    """
    spec = config["customers"]
    join_span = float(spec["join_window_fraction"]) * window_days * 86400.0
    low_ip, high_ip = spec["home_ips"]
    propensity_low, propensity_high = spec["login_propensity"]
    shared_probability = float(spec["shared_ip_probability"])

    customers: list[CustomerProfile] = []
    for index in range(count):
        customer_id = f"{prefix}cus_{index + 1:06d}"
        joined_at = window_start + timedelta(seconds=float(rng.uniform(0.0, join_span)))
        ip_count = int(rng.integers(int(low_ip), int(high_ip) + 1))
        customers.append(
            CustomerProfile(
                customer_id=customer_id,
                joined_at=joined_at,
                home_ips=tuple(
                    f"{prefix}ip_{customer_id}_{n}" for n in range(ip_count)
                ),
                login_propensity=float(rng.uniform(propensity_low, propensity_high)),
                on_shared_ip=bool(rng.random() < shared_probability),
            )
        )
    return customers


def build_covering_merchants(
    rng: np.random.Generator, config: dict
) -> list[MerchantProfile]:
    """Allocate merchants so every declared kind is realized at least once.

    Dataset V2 and Blind v1.0 both sampled ``count`` kinds by weight WITH
    REPLACEMENT, which silently left declared kinds -- ``travel`` in
    development, ``ticketing_events`` in blind -- with zero merchants and zero
    devices. Coverage first, then the remaining slots by weight.
    """
    kinds = config["kinds"]
    names = sorted(kinds)
    count = int(config["count"])
    if count < len(names):
        raise DatasetV3Error(
            f"{len(names)} merchant kinds declared but only {count} slots; "
            "every declared kind must be realized"
        )
    weights = np.array([float(kinds[name]["weight"]) for name in names], dtype=float)
    extra = list(rng.choice(names, size=count - len(names), p=weights / weights.sum()))
    calendar = resolve_calendar(config)
    merchants = [
        make_merchant(rng, index, str(kind), kinds[kind], calendar)
        for index, kind in enumerate(names + extra)
    ]
    realized = {merchant.kind for merchant in merchants}
    missing = sorted(set(names) - realized)
    if missing:  # pragma: no cover - defensive; coverage is constructive above
        raise DatasetV3Error(f"merchant kinds were not realized: {missing}")
    return merchants


def login_affinity(config: dict, kind: str) -> float:
    """How likely a shopper at this kind of business is signed in.

    A property of the merchant, never of the actor -- and merchant kind is
    still not a model feature.
    """
    return float(config["kinds"][kind].get("login_affinity", 1.0))
