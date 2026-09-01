"""Synthetic merchant profiles.

A merchant describes a business, not a risk level: it sets how large a
typical payment is, how often the gateway declines, whether campaigns run,
and how much of its traffic shares an egress IP. Attack actors are assigned
to ordinary merchants too, so merchant kind never implies the label.

These profiles exist only to give the generated traffic realistic variety.
The runtime does not model merchants beyond protecting the identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np


@dataclass(frozen=True)
class MerchantProfile:
    merchant_id: str
    kind: str
    typical_amount: float
    amount_spread: float
    base_success_rate: float
    campaign_share: float
    returning_customer_rate: float
    shared_ip_pressure: float
    #: "known" if this merchant kind existed during development, "unseen" if
    #: the archetype is new to the blind benchmark. Evaluation grouping only:
    #: merchant kind is not a model feature.
    origin: str = "known"
    #: Absolute (start, end) campaign windows on the shared calendar. Every
    #: request inside one is flagged `campaign_active`, regardless of who
    #: makes it -- so a flash-sale shopper and an attacker hiding in the same
    #: sale genuinely share the merchant's context.
    campaign_windows: tuple[tuple[datetime, datetime], ...] = ()

    def draw_amount(self, rng: np.random.Generator, multiplier: float = 1.0) -> float:
        """A typical purchase: lognormal around the merchant's centre so the
        distribution has a realistic right tail and overlaps other kinds."""
        value = rng.lognormal(np.log(self.typical_amount), self.amount_spread)
        return round(float(min(max(value * multiplier, 1.0), 1_000_000.0)), 2)

    def in_campaign(self, moment: datetime) -> bool:
        return any(start <= moment < end for start, end in self.campaign_windows)


def _campaign_windows(
    rng: np.random.Generator, share: float, calendar: dict
) -> tuple[tuple[datetime, datetime], ...]:
    """Lay a merchant's campaigns across the shared calendar.

    ``share`` is roughly the fraction of calendar days the merchant is running
    a campaign, so a flash-sale merchant is on sale often and a subscription
    merchant almost never. Windows are placed on a deterministic grid and then
    jittered, which is enough realism without a campaign service.
    """
    start = calendar["start"]
    total_days = int(calendar["days"])
    length_low, length_high = calendar["window_days"]
    if share <= 0 or total_days <= 0:
        return ()
    mean_length = (length_low + length_high) / 2
    count = int(round(share * total_days / max(mean_length, 1)))
    if count <= 0:
        return ()
    stride = total_days / count
    windows = []
    for index in range(count):
        offset = index * stride + float(rng.uniform(0, stride * 0.6))
        length = float(rng.uniform(length_low, length_high))
        opens = start + timedelta(days=offset)
        windows.append((opens, opens + timedelta(days=length)))
    return tuple(windows)


def resolve_calendar(config: dict) -> dict:
    calendar = dict(config["campaign_calendar"])
    calendar["start"] = (
        calendar["start"]
        if isinstance(calendar["start"], datetime)
        else datetime.fromisoformat(str(calendar["start"]))
    )
    return calendar


def make_merchant(
    rng: np.random.Generator, index: int, kind: str, spec: dict, calendar: dict
) -> MerchantProfile:
    """Draw one merchant's parameters from its kind's declared ranges.

    Kept separate from the kind *allocation* so a caller can decide which
    kinds exist without changing how a merchant of a given kind is drawn.
    """
    share = float(rng.uniform(*spec["campaign_share"]))
    return MerchantProfile(
        merchant_id=f"mer_{index + 1:03d}",
        kind=str(kind),
        typical_amount=float(rng.uniform(*spec["typical_amount"])),
        amount_spread=float(rng.uniform(*spec["amount_spread"])),
        base_success_rate=float(rng.uniform(*spec["base_success_rate"])),
        campaign_share=share,
        returning_customer_rate=float(rng.uniform(*spec["returning_customer_rate"])),
        shared_ip_pressure=float(rng.uniform(*spec["shared_ip_pressure"])),
        origin=str(spec.get("origin", "known")),
        campaign_windows=_campaign_windows(rng, share, calendar),
    )


def build_merchants(rng: np.random.Generator, config: dict) -> list[MerchantProfile]:
    """Development allocation: sample `count` kinds by weight, with replacement.

    Acceptable there because the development config declares far more merchant
    slots than kinds, so every kind is realized in practice. The blind
    benchmark cannot rely on that and uses its own allocation -- see
    `blind_generator.build_blind_merchants`.
    """
    kinds = config["kinds"]
    calendar = resolve_calendar(config)
    names = sorted(kinds)
    weights = np.array([float(kinds[name]["weight"]) for name in names])
    weights = weights / weights.sum()
    chosen = rng.choice(names, size=int(config["count"]), p=weights)
    return [
        make_merchant(rng, index, str(kind), kinds[kind], calendar)
        for index, kind in enumerate(chosen)
    ]
