# Phase 2.6 Model v3.1 Feature Ablation & Root-Cause Hypotheses Report

**Status:** COMPLETE — FROZEN DIAGNOSTIC ABLATIONS
**Model Version:** `model-v3.1`
**Dataset:** Held-out Validation Split (`development-v4.1`)
**Feature Contract:** `merchant-visible-causal-3.1` (44 features)
**Ablations Evaluated:** 10 targeted configurations

---

## 1. Executive Summary

This report documents the targeted feature ablation experiments conducted on Model v3.1 (`hist_gb_2` under Feature Contract v3.1). Each ablation drops a specified functional group of features, retrains the candidate on the actor-safe TRAIN split with normalized device weights, and scores the held-out VALIDATION split.

These experiments systematically test Hypotheses A, B, C, and D formulated after Blind v2:
- **Hypothesis A:** **REJECTED / NOT SUPPORTED AS THE SPECIFIC MECHANISM.** Dropping card-diversity ratio, card-change ratio, or both does *not* recreate subscription dunning false positives; dunning remains at 0.00% REVIEW+ and 0.00% BLOCK. However, the broader relationship/entity feature family as a whole provides essential multi-scenario discriminative power.
- **Hypothesis B:** **REJECTED.** Weak guest attacks are not primarily missed due to missing customer identity. Dropping `customer_id_present` leaves weak guest recall virtually unchanged at 96.30% REVIEW+, while increasing legitimate customer friction.
- **Hypothesis C:** **SUPPORTED, BUT MODEST EFFECT.** Historical trust/continuity features provide modest protective insulation for legitimate customers, but are not the sole or dominant stabilizing mechanism.
- **Hypothesis D:** **UNRESOLVED / NOT IMPLEMENTED.** The previously claimed merchant-relative features were mathematically invalid pseudo-features and were excised in Contract v3.1.

---

## 2. Targeted Ablation Results Table

All models were trained on the TRAIN split using 5-fold actor-safe grouped cross-validation and evaluated on the 6,000-device held-out VALIDATION split:

| Ablation Name | Dropped Count | Features Remaining | PR-AUC | $\Delta$ PR-AUC | ROC-AUC | Brier Score | ECE | Attack REVIEW+ | Legit REVIEW+ | Legit BLOCK |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`full_v3_1`** | **0** | **44** | **0.91686** | **Baseline** | **0.96925** | **0.04100** | **0.02143** | **93.49%** | **3.14%** | **0.14%** |
| `minus_card_diversity_ratio` | 1 | 43 | 0.91785 | +0.00099 | 0.96989 | 0.04077 | 0.02102 | 93.49% | 3.10% | 0.14% |
| `minus_card_change_ratio` | 1 | 43 | 0.91773 | +0.00087 | 0.96988 | 0.04077 | 0.02108 | 93.49% | 3.07% | 0.14% |
| `minus_both_card_ratios` | 2 | 42 | 0.91673 | -0.00013 | 0.96924 | 0.04101 | 0.02148 | 93.65% | 3.14% | 0.14% |
| `minus_session_churn` | 1 | 43 | 0.91741 | +0.00055 | 0.96962 | 0.04075 | 0.02047 | 93.49% | 2.93% | 0.14% |
| `minus_temporal_shape` | 4 | 40 | 0.91698 | +0.00012 | 0.96924 | 0.04098 | 0.02137 | 93.65% | 3.00% | 0.14% |
| `minus_long_horizon` | 4 | 40 | 0.91775 | +0.00089 | 0.96963 | 0.04071 | 0.02052 | 93.49% | 3.07% | 0.14% |
| `minus_trust_continuity` | 5 | 39 | 0.91503 | -0.00183 | 0.96860 | 0.04135 | 0.02030 | 93.33% | 3.28% | 0.21% |
| `minus_customer_identity_presence` | 1 | 43 | 0.90485 | -0.01201 | 0.96495 | 0.04369 | 0.02641 | 93.65% | 4.22% | 0.14% |
| `minus_relationship_entity` | 6 | 38 | **0.89356** | **-0.02330** | **0.96095** | **0.04618** | **0.02298** | **90.95%** | **3.55%** | **0.21%** |

---

## 3. Scenario-Level Effects Across Key Ablations

| Scenario Family | `full_v3_1` | `minus_card_ratios` | `minus_trust_continuity` | `minus_customer_id` | `minus_relationship_entity` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`subscription_dunning_hard` REVIEW+** | **0.00%** | **0.00%** | **0.00%** | **0.00%** | **0.00%** |
| **`subscription_dunning_hard` BLOCK** | **0.00%** | **0.00%** | **0.00%** | **0.00%** | **0.00%** |
| `persistent_card_problem_hard` REVIEW+ | 4.61% | 4.61% | 4.96% | 6.03% | **6.74%** |
| `persistent_card_problem_hard` BLOCK | 0.00% | 0.00% | 0.00% | 0.00% | **0.35%** |
| `network_retry_storm_hard` REVIEW+ | 2.79% | 2.79% | 2.79% | 2.79% | 2.44% |
| `cross_device_weak_guest` REVIEW+ | 96.30% | 96.30% | 96.30% | 96.30% | **95.56%** |
| `cross_device_partial` REVIEW+ | 97.33% | 97.33% | 96.67% | 97.33% | **96.67%** |
| `distributed_bot_campaign` REVIEW+ | 76.79% | 76.79% | 76.79% | 76.79% | 76.79% |
| `distributed_bot_campaign` BLOCK | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |

---

## 4. Empirical Verdict on Hypotheses

### Hypothesis A: Card Diversity Gating as Specific Dunning Solution
> *Statement:* “Card diversity features (`card_diversity_ratio_7d`, `card_change_after_decline_ratio_7d`) were the primary specific mechanism preventing subscription-dunning false positives.”

- **Empirical Evidence:** Removing `card_diversity_ratio_7d`, `card_change_after_decline_ratio_7d`, or both simultaneously leaves `subscription_dunning_hard` friction at exactly **0.00% REVIEW+ and 0.00% BLOCK**. The model does not re-penalize subscription dunning when these two specific ratios are dropped.
- **Broader Family Role:** When the entire relationship/entity family is dropped (`minus_relationship_entity`), PR-AUC drops from 0.91686 to 0.89356 (-0.0233), attack REVIEW+ drops from 93.49% to 90.95%, legitimate REVIEW+ worsens from 3.14% to 3.55%, and `persistent_card_problem_hard` review rate rises from 4.61% to 6.74% with legitimate blocks appearing (0.35%).
- **Verdict:** **REJECTED / NOT SUPPORTED AS THE SPECIFIC MECHANISM.** While relationship/entity features are essential to multi-scenario discriminative performance, the specific claim that the two card-ratio features uniquely solved dunning is disproven by the ablation evidence.

---

### Hypothesis B: Weak Guest Attacks Escaped Due to Missing Customer Identity
> *Statement:* “Weak guest attacks were missed primarily because customer identity was absent, causing the customer entity layer to be uninformative.”

- **Empirical Evidence:** Dropping `customer_id_present` (`minus_customer_identity_presence`) leaves `cross_device_weak_guest` REVIEW+ recall unchanged at **96.30%**. Instead, legitimate friction increases significantly: legitimate REVIEW+ rises from 3.14% to 4.22%, and `persistent_card_problem_hard` reviews rise from 4.61% to 6.03%. PR-AUC falls by 0.0120 to 0.90485.
- **Verdict:** **REJECTED.** Customer identity presence operates as a valuable negative-risk / trust prior for legitimate shoppers rather than an attack-detection gate. Weak guest attacks are identified by device-level attempt structure and IP/session dynamics, not by absence of `customer_id`.

---

### Hypothesis C: Historical Trust / Continuity Insulates Legitimate Retries
> *Statement:* “Historical trust and continuity signals reduce legitimate false positives on repeated declines.”

- **Empirical Evidence:** Removing trust/continuity features (`customer_successful_checkouts_30d`, `customer_age_seconds`, `successful_checkouts_30d`, `device_age_seconds`, `seconds_since_last_success`) produces a modest but clear degradation:
  - PR-AUC declines from 0.91686 to 0.91503 (-0.00183)
  - Legitimate REVIEW+ increases from 3.14% to 3.28%
  - Legitimate BLOCK increases by 50% from 0.14% to 0.21%
  - `persistent_card_problem_hard` REVIEW+ increases from 4.61% to 4.96%
- **Verdict:** **SUPPORTED, BUT MODEST EFFECT.** Historical trust provides a meaningful and statistically observable protective cushion against false friction, though it is not the sole stabilizing factor.

---

### Hypothesis D: Merchant-Relative Normalization Resolves Merchant Heterogeneity
> *Statement:* “Normalizing transaction velocity and amounts against merchant archetypes prevents cross-merchant miscalibration.”

- **Empirical Evidence:** The features originally introduced in Phase 2 to test this hypothesis (`merchant_relative_velocity_zscore` and `merchant_amount_log_ratio`) were mathematically invalid ungrounded transforms. Contract v3.1 properly removed them.
- **Verdict:** **UNRESOLVED / NOT IMPLEMENTED.** No valid merchant-relative feature is currently implemented in Contract v3.1; therefore, this hypothesis remains untested and cannot be claimed as supported.

---

## 5. Temporal Shape, Long Horizon, and Session Churn Redundancy

Ablation results for temporal-shape features, long-horizon counters, and session churn:
- `minus_temporal_shape`: PR-AUC changes from 0.91686 to 0.91698 (+0.00012)
- `minus_long_horizon`: PR-AUC changes from 0.91686 to 0.91775 (+0.00089)
- `minus_session_churn`: PR-AUC changes from 0.91686 to 0.91741 (+0.00055)

These families show minimal incremental ranking gain on the current synthetic development validation set, suggesting partial correlation with other velocity features under the current generator distribution.

---

## 6. Distributed Bot Campaign Stability

Across all 10 targeted ablations, `distributed_bot_campaign` performance remained virtually invariant:
- REVIEW+ Rate: **76.79%**
- BLOCK Rate: **0.00%**
- Mean Max Score: ~0.71

This illustrates a structural characteristic: in extremely diffuse campaigns (50 devices submitting 1 attempt each), per-device evidence is insufficient to exceed the evidence gate required for hard blocking (`block_evidence >= 2`). Detecting and blocking diffuse multi-merchant campaigns requires cross-merchant graph intelligence, which is outside the single-merchant scope of Card-Testing Sentinel.

---

## 7. Explicit Warning Against Post-Hoc Feature Pruning

> [!WARNING]
> Although several individual feature ablations (`minus_temporal_shape`, `minus_long_horizon`, `minus_card_diversity_ratio`) exhibit minor nominal PR-AUC improvements (+0.0001 to +0.0010) on the development validation set, **NO FEATURES WILL BE PRUNED AT THIS STAGE**.
>
> Pruning features based on held-out development validation data would constitute post-hoc dataset over-fitting immediately prior to evaluation against the Post-Blind Remediation Stress Suite (PBRSS-v1). The 44-feature contract `merchant-visible-causal-3.1` remains frozen.
