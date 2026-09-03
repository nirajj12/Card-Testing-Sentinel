# Phase 2 Model v3 Feature Ablation & Root-Cause Hypotheses Report

> **SUPERSEDED / REJECTED DEVELOPMENT EVIDENCE.** Actor leakage and two
> invalid merchant features make the causal claims below unusable. They are
> retained as an audit trail, not accepted conclusions.

**Date:** September 2026  
**Status:** SUPERSEDED — HYPOTHESES NOT ESTABLISHED BY THIS RUN  
**Model Version:** `model-v3`  
**Dataset Split:** Held-out Validation Split (`features_v3.csv`)

---

## 1. Executive Summary

This study documents the empirical ablation experiments conducted on Model v3 (`logistic_C5.0` under Feature Contract v3). Each ablation removes a functional feature family, retrains the model on the full TRAIN split using balanced device weights, and evaluates the performance on the held-out VALIDATION split.

The results provide definitive empirical evidence resolving the core hypotheses formulated in `docs/post_blind_v2_diagnosis.md`:
1. **Hypothesis A Confirmed:** Repeated failure signals without card diversity signals are indeed the driving mechanism behind subscription dunning false positives. Removing relationship and card diversity features degrades PR-AUC by 0.0639 and collapses precision.
2. **Hypothesis B Confirmed:** Weak guest / cross-device attacks are identified through session churn, card rotation, and merchant velocity normalization even when persistent customer identity is absent.
3. **Hypothesis C Confirmed:** Trust and continuity features protect established accounts and insulate genuine retries from accumulating wrongful friction.
4. **Hypothesis D Confirmed:** Merchant-relative velocity normalization is critical; removing it causes a 0.0564 drop in PR-AUC.

---

## 2. Feature Family Ablation Table

| Feature Family Ablation | Dropped Features Count | Remaining Features Count | PR-AUC | $\Delta$ PR-AUC | ROC-AUC | Brier Score | ECE |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Full Model v3** | **0** | **46** | **0.8684** | **Baseline** | **0.9467** | **0.0556** | **0.0175** |
| **minus Relationship & Entity** | 6 | 40 | **0.8045** | **-0.0639** | 0.9232 | 0.0712 | 0.0218 |
| **minus Merchant-Relative** | 2 | 44 | **0.8119** | **-0.0565** | 0.9245 | 0.0712 | 0.0244 |
| **minus Temporal Shape** | 4 | 42 | **0.8580** | **-0.0104** | 0.9427 | 0.0584 | 0.0167 |
| **minus Trust & Continuity** | 5 | 41 | **0.8619** | **-0.0065** | 0.9431 | 0.0571 | 0.0146 |
| **minus Long-Horizon Context** | 4 | 42 | **0.8643** | **-0.0041** | 0.9451 | 0.0567 | 0.0163 |

---

## 3. Detailed Feature Family Analysis

### A. Relationship & Entity Features (`minus_relationship_entity`)
- **Dropped Features:** `card_diversity_ratio_7d`, `card_change_after_decline_ratio_7d`, `distinct_card_last4_7d`, `distinct_card_networks_7d`, `card_change_after_decline_7d`, `session_churn_rate_24h`.
- **Impact:** Largest PR-AUC degradation across all ablations (-0.0639, from 0.8684 to 0.8045). Brier score deteriorates from 0.0556 to 0.0712 (+28%).
- **Mechanism:** Without card diversity and session churn, the model falls back to raw decline counts (`failures_7d`, `decline_streak`). Because repeated card declines occur in both card testing and genuine subscription billing failures, removing entity relationship features strips the model of its ability to distinguish single-card genuine retries from multi-card testing.

### B. Merchant-Relative Features (`minus_merchant_relative`)
- **Dropped Features:** `merchant_relative_velocity_zscore`, `merchant_amount_log_ratio`.
- **Impact:** Second largest degradation (-0.0565 PR-AUC, from 0.8684 to 0.8119).
- **Mechanism:** Velocity signals (e.g. 5 requests in 5 minutes) mean very different things at a flash-sale merchant versus a luxury goods store. Merchant-relative z-scoring normalizes these bursts against the merchant's baseline, preventing flash-sale false positives while catching low-velocity patient testing on slow merchants.

### C. Temporal Shape Features (`minus_temporal_shape`)
- **Dropped Features:** `median_inter_attempt_gap_seconds_24h`, `gap_coefficient_of_variation_24h`, `median_gap_between_attempts`, `gap_variability`.
- **Impact:** Modest degradation (-0.0104 PR-AUC).
- **Mechanism:** Inter-attempt timing regularity separates automated bot traffic (low CV, tight cadences) from human shoppers (high variance, irregular pauses). Removing temporal shape slightly harms precision on automated retry bots.

### D. Trust & Continuity Features (`minus_trust_continuity`)
- **Dropped Features:** `customer_successful_checkouts_30d`, `customer_age_seconds`, `successful_checkouts_30d`, `device_age_seconds`, `seconds_since_last_success`.
- **Impact:** Modest aggregate PR-AUC drop (-0.0065), but noticeable increase in legitimate device review rates on established customers.
- **Mechanism:** Trust signals provide negative risk evidence, holding down scores for shoppers with an unbroken record of successful checkouts even when their card experiences a temporary billing decline.

---

## 4. Phase 1 Root-Cause Hypotheses Verification

### Hypothesis A: Repeated Failure vs. Card Diversity
> *Hypothesis:* In Model v2 / Blind v2, linear failure accumulation (`failures_7d`, `decline_streak`) penalized subscription dunning because the model lacked card-diversity gating to distinguish 4 retries on 1 card from 4 retries across 4 cards.

**Verification Result: CONFIRMED.**
- In Model v3, incorporating `card_diversity_ratio_7d` and `card_change_after_decline_ratio_7d` reduced `subscription_dunning_hard` friction to **0.0% REVIEW+ and 0.0% BLOCK** (mean max score: 0.0245).
- In the ablation removing relationship features, the model loses this differentiation and dunning friction surges.
- Counterfactual twin pairs (`CP-01`, `CP-02`) confirm that keeping all request parameters identical while toggling single-card vs 4-card rotation changes the predicted score from 0.02 to 0.99!

### Hypothesis B: Weak Guest / Cross-Device Attack Visibility
> *Hypothesis:* Model v2 struggled on `cross_device_weak_guest` (historical Blind v2: **20.7921% REVIEW+ (21/101), 0.9901% BLOCK (1/101)**) because attackers rotated devices and sessions without logging in, rendering customer-level features blank.

**Verification Result: CONFIRMED.**
- In Model v3, `cross_device_weak_guest` achieved **94.1% REVIEW+ and 73.5% BLOCK**.
- Features such as `session_churn_rate_24h`, `card_diversity_ratio_7d`, and `merchant_relative_velocity_zscore` identify distributed campaigns at precheck time even when `customer_id` is null.

### Hypothesis C: Historical Trust Reduces Legitimate Friction
> *Hypothesis:* Established historical successful transactions can suppress false alarms on legitimate bursts.

**Verification Result: CONFIRMED.**
- Established returning customers (`normal_returning_customer`) and multi-device customers (`multi_device_customer_v4`) experienced $\le 0.6\%$ REVIEW+ and 0.0% BLOCK under Model v3.

### Hypothesis D: Merchant Context Normalization
> *Hypothesis:* Absolute transaction amounts and absolute velocity thresholds cause merchant-specific bias unless normalized relative to merchant archetype.

**Verification Result: CONFIRMED.**
- Removing merchant-relative features caused an immediate 0.0565 PR-AUC collapse, confirming that relative velocity and relative amounts prevent cross-merchant miscalibration.
