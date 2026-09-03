# Model v3.1 Feature Ablation Report

## Goal

Evaluate 10 targeted feature ablations on Model v3.1 to test empirical hypotheses formed after Blind v2 and verify feature group contributions before freezing the 44-feature contract.

## Setup

- **Model:** `model-v3.1` (`hist_gb_2`)
- **Dataset:** `development-v4.1` (Held-out 6,000-device validation split)
- **Baseline Feature Contract:** `merchant-visible-causal-3.1` (44 features)
- **Ablation Methodology:** Dropped specified functional groups, retrained on TRAIN with normalized device weights, and scored the validation split.

## What I Tested

- **Card Diversity Ratios:** Dropped `card_diversity_ratio_7d`, `card_change_after_decline_ratio_7d`, or both to test whether card ratios uniquely solved subscription dunning false friction.
- **Customer Identity Presence:** Dropped `customer_id_present` to test whether guest fraud was missed due to unauthenticated checkout sessions.
- **Trust and Continuity:** Dropped 5 historical trust signals (`customer_successful_checkouts_30d`, `customer_age_seconds`, `successful_checkouts_30d`, `device_age_seconds`, `seconds_since_last_success`) to test legitimate retry insulation.
- **Relationship and Entity Family:** Dropped all 6 entity/card relationship features to measure holistic multi-card discrimination.
- **Temporal Shape and Velocity:** Tested session churn, inter-attempt intervals, and long-horizon transaction counters.

## Results

### 1. Ablation Comparison Across All 10 Configurations

| Configuration | Dropped | Features Left | PR-AUC | $\Delta$ PR-AUC | ROC-AUC | Brier Score | ECE | Attack REVIEW+ | Legit REVIEW+ | Legit BLOCK |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`full_v3_1` (Baseline)** | **0** | **44** | **0.91686** | **Baseline** | **0.96925** | **0.04100** | **0.02143** | **93.49%** | **3.14%** | **0.14%** |
| `minus_card_diversity_ratio` | 1 | 43 | 0.91785 | +0.00099 | 0.96989 | 0.04077 | 0.02102 | 93.49% | 3.10% | 0.14% |
| `minus_card_change_ratio` | 1 | 43 | 0.91773 | +0.00087 | 0.96988 | 0.04077 | 0.02108 | 93.49% | 3.07% | 0.14% |
| `minus_both_card_ratios` | 2 | 42 | 0.91673 | -0.00013 | 0.96924 | 0.04101 | 0.02148 | 93.65% | 3.14% | 0.14% |
| `minus_session_churn` | 1 | 43 | 0.91741 | +0.00055 | 0.96962 | 0.04075 | 0.02047 | 93.49% | 2.93% | 0.14% |
| `minus_temporal_shape` | 4 | 40 | 0.91698 | +0.00012 | 0.96924 | 0.04098 | 0.02137 | 93.65% | 3.00% | 0.14% |
| `minus_long_horizon` | 4 | 40 | 0.91775 | +0.00089 | 0.96963 | 0.04071 | 0.02052 | 93.49% | 3.07% | 0.14% |
| `minus_trust_continuity` | 5 | 39 | 0.91503 | -0.00183 | 0.96860 | 0.04135 | 0.02030 | 93.33% | 3.28% | 0.21% |
| `minus_customer_identity_presence` | 1 | 43 | 0.90485 | -0.01201 | 0.96495 | 0.04369 | 0.02641 | 93.65% | 4.22% | 0.14% |
| `minus_relationship_entity` | 6 | 38 | **0.89356** | **-0.02330** | **0.96095** | **0.04618** | **0.02298** | **90.95%** | **3.55%** | **0.21%** |

### 2. Scenario-Level Effects

| Scenario Family | `full_v3_1` | `minus_card_ratios` | `minus_trust_continuity` | `minus_customer_id` | `minus_relationship_entity` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `subscription_dunning_hard` REVIEW+ | **0.00%** | 0.00% | 0.00% | 0.00% | 0.00% |
| `subscription_dunning_hard` BLOCK | **0.00%** | 0.00% | 0.00% | 0.00% | 0.00% |
| `persistent_card_problem_hard` REVIEW+ | **4.61%** | 4.61% | 4.96% | 6.03% | 6.74% |
| `persistent_card_problem_hard` BLOCK | **0.00%** | 0.00% | 0.00% | 0.00% | 0.35% |
| `network_retry_storm_hard` REVIEW+ | **2.79%** | 2.79% | 2.79% | 2.79% | 2.44% |
| `cross_device_weak_guest` REVIEW+ | **96.30%** | 96.30% | 96.30% | 96.30% | 95.56% |
| `cross_device_partial` REVIEW+ | **97.33%** | 97.33% | 96.67% | 97.33% | 96.67% |
| `distributed_bot_campaign` REVIEW+ | **76.79%** | 76.79% | 76.79% | 76.79% | 76.79% |
| `distributed_bot_campaign` BLOCK | **0.00%** | 0.00% | 0.00% | 0.00% | 0.00% |

## What the Results Mean

1. **Card Diversity Ratios (Hypothesis A — Rejected):** Removing `card_diversity_ratio_7d` and `card_change_after_decline_ratio_7d` did not reintroduce subscription dunning friction (dunning remained at 0.00% review and block). The individual ratios are not the sole mechanism preventing dunning false alarms, though the overall relationship family is critical.
2. **Customer Identity Presence (Hypothesis B — Rejected):** Dropping `customer_id_present` did not reduce weak guest attack recall (remained at 96.30%). Instead, it increased legitimate customer review friction from 3.14% to 4.22%. Identity presence functions as a trust prior for legitimate shoppers rather than an attack flag.
3. **Historical Trust Continuity (Hypothesis C — Supported, Modest):** Dropping historical trust counters lowered PR-AUC by 0.00183 and increased legitimate hard blocking from 0.14% to 0.21%. Trust signals provide meaningful protection against false friction during legitimate payment retries.
4. **Relationship / Entity Importance:** Dropping the broader entity family (`minus_relationship_entity`) caused the largest drop in PR-AUC (-0.02330), reduced attack recall to 90.95%, and increased legitimate blocks on card problem retries to 0.35%.
5. **No Post-Hoc Pruning:** Minor PR-AUC gains (+0.0001 to +0.0010) observed when dropping individual features were not used to prune the contract. Pruning against the validation set would cause post-hoc overfitting before external evaluation.

## Limitations

- **Development Validation Scope:** All ablations were evaluated on the synthetic Dataset v4.1 validation split.
- **Diffuse Attack Limit:** Across all 10 configurations, `distributed_bot_campaign` block rate remained at 0.00%. Local per-device feature ablations cannot overcome the structural limitation of single-attempt botnet attacks.

## Reproducibility

- **Ablation Definitions:** Stored in `artifacts/model_v3_1/targeted_ablations.json`
- **Feature Contract:** `configs/features_v3_1.yaml`
