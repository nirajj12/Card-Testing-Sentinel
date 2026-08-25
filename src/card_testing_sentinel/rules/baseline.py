"""Fixed, auditable rules baseline using only allowlisted causal features."""

import pandas as pd

SIGNALS = (
    "velocity_card_diversity",
    "repeated_declines",
    "rapid_card_switching",
    "near_minimum_probing",
    "continued_after_approval",
)


def score_rules(X: pd.DataFrame, config: dict) -> pd.DataFrame:
    rules = config["rules"]
    signals = pd.DataFrame(index=X.index)
    setting = rules["velocity"]
    signals[SIGNALS[0]] = X["attempts_trailing_60s"].ge(
        setting["attempts_trailing_60s"]
    ) & X["unique_cards_trailing_60s"].ge(setting["unique_cards_trailing_60s"])
    setting = rules["repeated_declines"]
    signals[SIGNALS[1]] = X["attempts_trailing_5min"].ge(
        setting["attempts_trailing_5min"]
    ) & X["decline_ratio_so_far"].ge(setting["decline_ratio_so_far"])
    setting = rules["rapid_card_switching"]
    signals[SIGNALS[2]] = X["attempts_trailing_5min"].ge(
        setting["attempts_trailing_5min"]
    ) & X["card_switch_rate"].ge(setting["card_switch_rate"])
    setting = rules["near_minimum_probing"]
    signals[SIGNALS[3]] = X["attempts_trailing_5min"].ge(
        setting["attempts_trailing_5min"]
    ) & X["amount_near_minimum_ratio_5min"].ge(
        setting["amount_near_minimum_ratio_5min"]
    )
    setting = rules["continued_after_approval"]
    signals[SIGNALS[4]] = X["attempts_after_first_approval"].ge(
        setting["attempts_after_first_approval"]
    ) & X["unique_cards_trailing_5min"].ge(setting["unique_cards_trailing_5min"])
    signals["rule_score"] = signals.loc[:, SIGNALS].sum(axis=1).astype(int)
    signals["reason_codes"] = signals.loc[:, SIGNALS].apply(
        lambda row: "|".join(name for name, active in row.items() if active), axis=1
    )
    return signals
