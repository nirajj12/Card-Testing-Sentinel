# Phase 2 Dataset v4 Audit & Shortcut Guardrail Report

> **SUPERSEDED.** Phase 2.5 found actor leakage and generator/specification
> mismatches not detected here. This is rejected historical evidence; Dataset
> v4.1 has a separate corrected audit.

**Date:** September 2026  
**Status:** PASSED  
**Dataset Artifact:** `data/generated/development_v4/`  
**Feature Contract:** `merchant-visible-causal-3` (46 features, SHA-256: `94c33005cb22d0d0cbbfe2e6878b668f237bfbfe88e2c0e98031d275727181ef`)

---

## 1. Executive Summary

Dataset v4 was generated in accordance with `docs/dataset_v4_postblind_spec.md`, `docs/dataset_v4_scenario_matrix.md`, and `docs/dataset_v4_audit_spec.md`. It directly remedies the behavioral deficiencies identified during the post-Blind v2 diagnosis:
- Entity coverage prioritized over raw volume: 12,000 devices generated across 20 merchants and 6 diverse merchant archetypes.
- All 8 critical scenario families comfortably exceeded their 250-device minimum quota.
- 20 matched counterfactual twin pairs (`CP-01` through `CP-20`) were generated to isolate card diversity, burst timing, and entity rotation.
- **Zero hard causal leakage** detected: target labels, scenario IDs, future gateway responses, and outcome fields are completely absent from precheck requests.
- **Shortcut Guardrails:** All 46 candidate features demonstrate PR-AUC < 0.80, preventing single-feature shortcut exploitation.

---

## 2. Dataset Composition & Dimensions

| Metric | Dataset v4 Value | Target Specification | Status |
| :--- | :--- | :--- | :--- |
| **Total Events** | 111,170 | ~100k - 130k | Validated |
| **Total Precheck Requests** | 46,264 | ~40k - 50k | Validated |
| **Total Devices** | 12,000 | 12,000 | Exact match |
| **Merchants Realized** | 20 | 20 across 6 archetypes | Validated |
| **Attack Device Fraction (Benchmark)** | 24.69% | ~25.0% | Validated |
| **Matched Counterfactual Pairs** | 20 pairs (40 twins) | Exactly 20 pairs | Validated |
| **Causal Lifecycle Events Validated** | 100% | Pydantic strict causal contract | Passed |

---

## 3. Critical Scenario Device Quota Verification

Every critical scenario family was required to achieve a minimum of 250–300 devices to ensure sufficient support for sub-cohort metrics and ablation studies:

| Scenario Name | Population | Devices Generated | Quota Minimum | Quota Status |
| :--- | :--- | :--- | :--- | :--- |
| `subscription_dunning_hard` | Legitimate | **1,108** | $\ge 250$ | **PASSED** (4.4x quota) |
| `persistent_card_problem_hard` | Legitimate | **962** | $\ge 250$ | **PASSED** (3.8x quota) |
| `network_retry_storm_hard` | Legitimate | **916** | $\ge 250$ | **PASSED** (3.7x quota) |
| `shared_household_device` | Legitimate | **854** | $\ge 250$ | **PASSED** (3.4x quota) |
| `cgnat_mobile_ip_storm` | Legitimate | **829** | $\ge 250$ | **PASSED** (3.3x quota) |
| `cross_device_weak_guest` | Attack | **580** | $\ge 250$ | **PASSED** (2.3x quota) |
| `cross_device_partial` | Attack | **578** | $\ge 250$ | **PASSED** (2.3x quota) |
| `distributed_bot_campaign` | Attack | **451** | $\ge 250$ | **PASSED** (1.8x quota) |

---

## 4. Single-Feature PR-AUC Audit Table

Single-feature models were fitted on the train split and evaluated on the validation split. Lifts are calculated relative to benchmark attack prevalence (0.2469).

| Feature Name | PR-AUC | ROC-AUC | Lift | Train-Val Stab | Diagnostic Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `card_diversity_ratio_7d` | 0.7458 | 0.8139 | 3.02x | 0.0172 | PASS_UNRESTRICTED |
| `distinct_card_last4_7d` | 0.6801 | 0.7712 | 2.75x | 0.0175 | PASS_UNRESTRICTED |
| `card_change_after_decline_7d` | 0.6388 | 0.7752 | 2.59x | 0.0141 | PASS_UNRESTRICTED |
| `distinct_card_networks_7d` | 0.6274 | 0.7524 | 2.54x | 0.0064 | PASS_UNRESTRICTED |
| `current_amount` | 0.5695 | 0.6859 | 2.31x | 0.0052 | REVIEW_METADATA_GUARDRAIL |
| `merchant_amount_log_ratio` | 0.5695 | 0.6859 | 2.31x | 0.0052 | PASS_UNRESTRICTED |
| `ip_changes_24h` | 0.5455 | 0.7297 | 2.21x | 0.0069 | PASS_UNRESTRICTED |
| `sessions_24h` | 0.5001 | 0.7254 | 2.03x | 0.0184 | PASS_UNRESTRICTED |
| `failures_7d` | 0.4880 | 0.7231 | 1.98x | 0.0200 | PASS_UNRESTRICTED |
| `card_change_after_decline_ratio_7d` | 0.4873 | 0.7592 | 1.97x | 0.0060 | PASS_UNRESTRICTED |
| `requests_7d` | 0.4721 | 0.6621 | 1.91x | 0.0217 | PASS_UNRESTRICTED |
| `prior_payments_24h` | 0.4367 | 0.6898 | 1.77x | 0.0199 | PASS_UNRESTRICTED |
| `requests_24h` | 0.4367 | 0.6898 | 1.77x | 0.0199 | PASS_UNRESTRICTED |
| `failures_per_active_day_7d` | 0.4348 | 0.7257 | 1.76x | 0.0272 | PASS_UNRESTRICTED |
| `recent_failures_24h` | 0.4208 | 0.6929 | 1.70x | 0.0206 | PASS_UNRESTRICTED |
| `requests_5m` | 0.4188 | 0.6897 | 1.70x | 0.0297 | PASS_UNRESTRICTED |
| `merchant_relative_velocity_zscore` | 0.4188 | 0.6897 | 1.70x | 0.0297 | PASS_UNRESTRICTED |
| `retry_after_decline_ratio_24h` | 0.4144 | 0.6476 | 1.68x | 0.0407 | PASS_UNRESTRICTED |
| `decline_streak` | 0.4016 | 0.6830 | 1.63x | 0.0142 | PASS_UNRESTRICTED |
| `gap_coefficient_of_variation_24h` | 0.3974 | 0.6465 | 1.61x | 0.0085 | PASS_UNRESTRICTED |
| `requests_60s` | 0.3948 | 0.6867 | 1.60x | 0.0386 | PASS_UNRESTRICTED |
| `customer_id_present` | 0.3746 | 0.7026 | 1.52x | 0.0087 | REVIEW_METADATA_GUARDRAIL |
| `amount_variation_24h` | 0.3459 | 0.6655 | 1.40x | 0.0014 | PASS_UNRESTRICTED |
| `customer_age_seconds` | 0.3309 | 0.6554 | 1.34x | 0.0097 | PASS_UNRESTRICTED |
| `low_amount_ratio_24h` | 0.3279 | 0.5610 | 1.33x | 0.0365 | PASS_UNRESTRICTED |
| `failure_ratio_24h` | 0.3189 | 0.6542 | 1.29x | 0.0033 | PASS_UNRESTRICTED |
| `successful_checkouts_30d` | 0.3020 | 0.6177 | 1.22x | 0.0051 | PASS_UNRESTRICTED |
| `customer_successful_checkouts_30d` | 0.2990 | 0.6138 | 1.21x | 0.0095 | PASS_UNRESTRICTED |
| `customer_failures_7d` | 0.2987 | 0.5005 | 1.21x | 0.0010 | PASS_UNRESTRICTED |
| `devices_per_ip_24h` | 0.2915 | 0.5526 | 1.18x | 0.0094 | PASS_UNRESTRICTED |
| `gap_variability` | 0.2750 | 0.5876 | 1.11x | 0.0013 | PASS_UNRESTRICTED |
| `seconds_since_last_success` | 0.2706 | 0.5661 | 1.10x | 0.0065 | PASS_UNRESTRICTED |
| `seconds_since_last_payment` | 0.2685 | 0.5972 | 1.09x | 0.0049 | PASS_UNRESTRICTED |
| `seconds_since_last_request` | 0.2685 | 0.5972 | 1.09x | 0.0049 | PASS_UNRESTRICTED |
| `is_new_device` | 0.2659 | 0.5467 | 1.08x | 0.0063 | PASS_UNRESTRICTED |
| `requests_per_ip_5m` | 0.2611 | 0.5246 | 1.06x | 0.0168 | PASS_UNRESTRICTED |
| `amount_delta` | 0.2594 | 0.5096 | 1.05x | 0.0026 | PASS_UNRESTRICTED |
| `median_inter_attempt_gap_seconds_24h` | 0.2587 | 0.5965 | 1.05x | 0.0029 | PASS_UNRESTRICTED |
| `customer_distinct_devices_7d` | 0.2561 | 0.5953 | 1.04x | 0.0075 | PASS_UNRESTRICTED |
| `requests_10s` | 0.2558 | 0.5194 | 1.04x | 0.0144 | PASS_UNRESTRICTED |
| `active_day_count_7d` | 0.2523 | 0.5144 | 1.02x | 0.0095 | PASS_UNRESTRICTED |
| `device_age_seconds` | 0.2523 | 0.5612 | 1.02x | 0.0076 | PASS_UNRESTRICTED |
| `session_churn_rate_24h` | 0.2506 | 0.5441 | 1.01x | 0.0104 | PASS_UNRESTRICTED |
| `ip_rotation_ratio_24h` | 0.2492 | 0.5472 | 1.01x | 0.0054 | PASS_UNRESTRICTED |
| `session_age_seconds` | 0.2484 | 0.5002 | 1.01x | 0.0033 | PASS_UNRESTRICTED |
| `median_gap_between_attempts` | 0.2275 | 0.5092 | 0.92x | 0.0040 | PASS_UNRESTRICTED |

**Diagnostic Observations:**
- Highest PR-AUC is `card_diversity_ratio_7d` at 0.7458 (well within the < 0.80 non-triviality ceiling).
- Metadata features (`customer_id_present`, `current_amount`) show modest correlation (PR-AUC 0.37 and 0.57) due to legitimate subscription requirements, but neither allows shortcut classification.
- All train-to-validation stability deltas are $\le 0.0407$, confirming consistent feature distributions across splits without covariate collapse.

---

## 5. Artifact Provenance & Checksums

The generated Dataset v4 files are saved in `data/generated/development_v4/` with exact SHA-256 digests:
- `raw_events.csv`: `cee32d1dfcf58bd6beb5edae75f86174893f28ebc010067cac35396124d8784a`
- `labels.csv`: `1123ea543cd997530d4571e1644b4b58670d07164c7a3c4067c8e249ecbf68f9`
- `features_v3.csv`: `3bd417d1e8a9832239a4744586279e8ddefe6b34bf9508763611b790061da964`
- `manifest.json`: `7b8b07f3fb4c365014df4cbd67a048b0269bc2f9b5c02b75f522afa9546d8f8a`
