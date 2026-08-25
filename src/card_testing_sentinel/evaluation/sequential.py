"""Unambiguous device-level metrics for post-authorization replay."""

from typing import Any

import pandas as pd


def device_summary(replay: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for device_id, part in replay.groupby("device_id", sort=True, observed=True):
        processed = part.loc[~part["potentially_prevented"]]
        reviews = processed.loc[
            processed["action"].eq("review"), "authorization_position"
        ]
        blocks = processed.loc[
            processed["action"].eq("block_next_attempt"), "authorization_position"
        ]
        first_review = int(reviews.iloc[0]) if len(reviews) else None
        first_block = int(blocks.iloc[0]) if len(blocks) else None
        before = (
            part.loc[part["authorization_position"].lt(first_block)]
            if first_block
            else part.iloc[0:0]
        )
        through = (
            part.loc[part["authorization_position"].le(first_block)]
            if first_block
            else part.iloc[0:0]
        )
        first_time = part["timestamp"].iloc[0]
        detection_time = (
            part.loc[part["authorization_position"].eq(first_block), "timestamp"]
            if first_block
            else pd.Series(dtype="datetime64[ns]")
        )
        rows.append(
            {
                "device_id": device_id,
                "population": str(part["population"].iloc[0]),
                "attack_subtype": None
                if pd.isna(part["attack_subtype"].iloc[0])
                else str(part["attack_subtype"].iloc[0]),
                "scenario_exposures": "|".join(
                    sorted(part["scenario_tag"].dropna().astype(str).unique())
                ),
                "label": int(part["true_label"].iloc[0]),
                "authorization_count": int(len(part)),
                "first_review_position": first_review,
                "first_block_position": first_block,
                "ever_review_or_higher": bool(first_review or first_block),
                "ever_blocked": bool(first_block),
                "review_only_without_block": bool(first_review and not first_block),
                "blocked_after_earlier_review": bool(
                    first_block and first_review and first_review < first_block
                ),
                "block_on_first_authorization": first_block == 1,
                "never_detected": first_block is None,
                "attempts_before_detection": first_block - 1 if first_block else None,
                "attempts_processed_through_detection": first_block,
                "distinct_cards_before_detection_attempt": int(
                    before["card_token"].nunique()
                )
                if first_block
                else None,
                "distinct_cards_processed_through_detection": int(
                    through["card_token"].nunique()
                )
                if first_block
                else None,
                "seconds_to_detection": float(
                    (detection_time.iloc[0] - first_time).total_seconds()
                )
                if first_block
                else None,
                "remaining_recorded_attempts_after_detection": int(
                    len(part) - first_block
                )
                if first_block
                else 0,
            }
        )
    return pd.DataFrame(rows)


def _rate(part: pd.DataFrame, field: str) -> dict[str, Any]:
    numerator = int(part[field].sum())
    denominator = int(len(part))
    return {
        "numerator_devices": numerator,
        "denominator_devices": denominator,
        "rate": numerator / denominator if denominator else None,
        "rate_granularity": 1 / denominator if denominator else None,
    }


def sequential_metrics(
    summary: pd.DataFrame, replay: pd.DataFrame, cutoffs: list[int]
) -> dict[str, Any]:
    attackers = summary.loc[summary["label"].eq(1)]
    legitimate = summary.loc[summary["label"].eq(0)]
    detected = attackers.loc[attackers["ever_blocked"]]
    coverage = _rate(attackers, "ever_blocked")
    within = {
        str(k): {
            "numerator_devices": int(attackers["first_block_position"].le(k).sum()),
            "denominator_devices": int(len(attackers)),
            "rate": float(
                attackers["first_block_position"].le(k).sum() / len(attackers)
            )
            if len(attackers)
            else None,
        }
        for k in cutoffs
    }
    position = detected["first_block_position"].astype(float)
    seconds = detected["seconds_to_detection"].astype(float)

    def stats(values: pd.Series) -> dict[str, float | None]:
        return (
            {
                "median": float(values.median()),
                "mean": float(values.mean()),
                "p90": float(values.quantile(0.9)),
                "maximum": float(values.max()),
            }
            if len(values)
            else {"median": None, "mean": None, "p90": None, "maximum": None}
        )

    subgroup = {}
    groups = {
        "normal": legitimate["population"].eq("normal"),
        "flash_sale": legitimate["population"].eq("flash_sale"),
        "normal_bad_luck": legitimate["scenario_exposures"]
        .str.split("|")
        .apply(lambda values: "normal_bad_luck" in values),
        "flash_hard_retry": legitimate["scenario_exposures"]
        .str.split("|")
        .apply(lambda values: "flash_hard_retry" in values),
    }
    for name, mask in groups.items():
        part = legitimate.loc[mask]
        subgroup[name] = {
            "ever_review_or_higher": _rate(part, "ever_review_or_higher"),
            "ever_blocked": _rate(part, "ever_blocked"),
        }
    subtype = {}
    for name in ("burst", "evasive", "patient"):
        part = attackers.loc[attackers["attack_subtype"].eq(name)]
        subtype[name] = {
            "detected": _rate(part, "ever_blocked"),
            "never_detected_devices": int(part["never_detected"].sum()),
        }
    processed = replay.loc[~replay["potentially_prevented"]]
    return {
        "attacker_block_coverage": coverage,
        "attacker_review_or_higher_coverage": _rate(attackers, "ever_review_or_higher"),
        "detected_within_attempt": within,
        "total_attacker_devices": int(len(attackers)),
        "detected_attacker_devices": int(len(detected)),
        "never_detected_attacker_devices": int(attackers["never_detected"].sum()),
        "never_detected_rate": float(attackers["never_detected"].mean())
        if len(attackers)
        else None,
        "detection_attempt_position": stats(position),
        "seconds_to_detection": stats(seconds),
        "attempts_processed_through_detection": stats(
            detected["attempts_processed_through_detection"].astype(float)
        ),
        "distinct_cards_before_detection_attempt": stats(
            detected["distinct_cards_before_detection_attempt"].astype(float)
        ),
        "distinct_cards_processed_through_detection": stats(
            detected["distinct_cards_processed_through_detection"].astype(float)
        ),
        "replay_estimated_potentially_preventable_attempts": int(
            detected["remaining_recorded_attempts_after_detection"].sum()
        ),
        "legitimate_overall": {
            "ever_review_or_higher": _rate(legitimate, "ever_review_or_higher"),
            "ever_blocked": _rate(legitimate, "ever_blocked"),
            "review_only_without_block": _rate(legitimate, "review_only_without_block"),
            "blocked_after_earlier_review": _rate(
                legitimate, "blocked_after_earlier_review"
            ),
            "block_on_first_authorization": _rate(
                legitimate, "block_on_first_authorization"
            ),
        },
        "legitimate_subgroups": subgroup,
        "attacker_subtypes": subtype,
        "raw_alerts": {
            "review_rows": int(processed["action"].eq("review").sum()),
            "block_rows": int(processed["action"].eq("block_next_attempt").sum()),
            "authorization_rows": int(len(replay)),
            "alerts_per_1000_authorization_rows": float(
                processed["action"].isin(["review", "block_next_attempt"]).sum()
                * 1000
                / len(replay)
            ),
        },
    }
