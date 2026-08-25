import itertools
import json


def enumerate_policy_grid(config: dict) -> list[dict]:
    candidates = []
    sequence = 0
    rules = config["families"]["rules_only"]
    for review, block in itertools.product(rules["review_scores"], rules["block_scores"]):
        if review >= block:
            continue
        candidates.append({"candidate_id": f"policy_{sequence:03d}", "family": "rules_only", "review_score": int(review), "block_score": int(block)})
        sequence += 1
    ml = config["families"]["ml_only"]
    for review, block in itertools.product(ml["review_thresholds"], ml["block_thresholds"]):
        if review >= block:
            continue
        candidates.append({"candidate_id": f"policy_{sequence:03d}", "family": "ml_only", "review_threshold": float(review), "block_threshold": float(block)})
        sequence += 1
    combined = config["families"]["combined"]
    for review, block, review_score, support in itertools.product(
        combined["review_thresholds"],
        combined["block_thresholds"],
        combined["review_scores"],
        combined["block_support_scores"],
    ):
        if review >= block or review_score >= support:
            continue
        candidates.append(
            {
                "candidate_id": f"policy_{sequence:03d}",
                "family": "combined",
                "review_threshold": float(review),
                "block_threshold": float(block),
                "review_score": int(review_score),
                "block_support_score": int(support),
            }
        )
        sequence += 1
    return candidates


def choose_action(candidate: dict, probability: float, rule_score: int) -> str:
    family = candidate["family"]
    if family == "rules_only":
        if rule_score >= candidate["block_score"]:
            return "block_current_attempt"
        if rule_score >= candidate["review_score"]:
            return "review"
        return "allow"
    if family == "ml_only":
        if probability >= candidate["block_threshold"]:
            return "block_current_attempt"
        if probability >= candidate["review_threshold"]:
            return "review"
        return "allow"
    if probability >= candidate["block_threshold"] and rule_score >= candidate["block_support_score"]:
        return "block_current_attempt"
    if probability >= candidate["review_threshold"] or rule_score >= candidate["review_score"]:
        return "review"
    return "allow"


def policy_complexity(candidate: dict) -> int:
    return {"rules_only": 0, "ml_only": 1, "combined": 2}[candidate["family"]]


def conservative_threshold_score(candidate: dict) -> float:
    values = [value for key, value in candidate.items() if "threshold" in key or "score" in key]
    return float(sum(values))


def comparison_tuple(metrics: dict, candidate: dict) -> tuple:
    delay = metrics["median_processed_authorizations_before_first_action"]
    if delay != delay:
        delay = 1e12
    return (
        metrics["worst_subtype_review_coverage"],
        metrics["macro_subtype_review_coverage"],
        metrics["worst_subtype_block_coverage"],
        metrics["macro_subtype_block_coverage"],
        -delay,
        -metrics["legitimate_blocks"],
        -metrics["legitimate_review_or_higher"],
        -policy_complexity(candidate),
        conservative_threshold_score(candidate),
        json.dumps(candidate, sort_keys=True),
    )

