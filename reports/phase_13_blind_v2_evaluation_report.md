# Phase 13 — One-Time Blind v2 Evaluation

## 1. Pre-evaluation freeze verification

Passed before Model v2 was loaded. Every Blind v2 source/data hash and every
development anchor matched the Phase 12 freeze. Fresh causal replay matched all
15364 frozen feature rows.

## 2. Exact first-score and consumption timestamp

`2026-08-31T18:11:07.909388+00:00`. The consumption record
was written immediately after the first successful scoring call and before any
metric was calculated or displayed.

## 3. Lifecycle state

`evaluated = true`, `consumed = true`, and `post_blind_tuning = false`.

## 4. Model v2 aggregate metrics

- PR-AUC: 0.487127
- ROC-AUC: 0.735120
- Brier: 0.152069
- Log loss: 0.500684
- ECE: 0.117139

Metrics are request-level with total weight one per device, matching development.

## 5. Calibration metrics

ECE is 0.117139; the ten fixed equal-width calibration bins are stored
in `artifacts/evaluation/blind_v2_calibration.csv`. No calibrator was fitted.

## 6. Fixed threshold table

| threshold | attack_device_recall | legitimate_device_fpr | device_precision | device_flagged_fraction | attack_devices_detected | legitimate_devices_flagged | flagged_devices |
|---|---|---|---|---|---|---|---|
| 0.3 | 0.85 | 0.358438 | 0.372195 | 0.45675 | 680 | 1147 | 1827 |
| 0.4 | 0.81375 | 0.295938 | 0.407384 | 0.3995 | 651 | 947 | 1598 |
| 0.5 | 0.78875 | 0.244375 | 0.446568 | 0.35325 | 631 | 782 | 1413 |
| 0.6 | 0.76375 | 0.2025 | 0.485306 | 0.31475 | 611 | 648 | 1259 |
| 0.7 | 0.72375 | 0.166563 | 0.520683 | 0.278 | 579 | 533 | 1112 |
| 0.75 | 0.705 | 0.149062 | 0.541787 | 0.26025 | 564 | 477 | 1041 |
| 0.8 | 0.67875 | 0.12875 | 0.568586 | 0.23875 | 543 | 412 | 955 |
| 0.9 | 0.48625 | 0.064375 | 0.653782 | 0.14875 | 389 | 206 | 595 |

These eight thresholds were fixed in the Phase 13 instruction and are diagnostic
only. No replacement operating point was selected.

## 7. Frozen Policy v2 aggregate metrics

- Attack REVIEW+: 564/800 (70.50%)
- Attack BLOCK: 273/800 (34.12%)
- Legitimate REVIEW+: 477/3200 (14.91%)
- Legitimate BLOCK: 163/3200 (5.09%)
- Attempt actions: {'allow': {'count': 11844, 'rate': 0.770893}, 'review': {'count': 2198, 'rate': 0.143062}, 'block': {'count': 1322, 'rate': 0.086045}}

## 8. Operating-target PASS/FAIL

- Attack REVIEW+ >= 70%: **PASS**
- Legitimate REVIEW+ <= 6%: **FAIL**
- Legitimate BLOCK <= 1%: **FAIL**

## 9. Confidence intervals

Wilson 95% intervals: attack REVIEW+ {'low': 0.672479, 'high': 0.735562}, attack BLOCK
{'low': 0.309224, 'high': 0.374794}, legitimate REVIEW+ {'low': 0.137144, 'high': 0.161823}, and
legitimate BLOCK {'low': 0.043844, 'high': 0.059108}. Small family estimates have materially
wider uncertainty and should not be read as precise production rates.

## 10. All attack-family metrics

| scenario | population | devices | requests | reviewed_devices | blocked_devices | review_or_higher_rate | block_rate | never_detected_devices | median_first_review_attempt | p90_first_review_attempt | median_first_block_attempt | p90_first_block_attempt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| burst_pause_burst_v2 | attack | 24 | 284 | 23 | 22 | 0.958333 | 0.916667 | 1.0 | 5.0 | 6.0 | 7.0 | 8.9 |
| cross_device_partial | attack | 133 | 378 | 54 | 5 | 0.406015 | 0.037594 | 79.0 | 3.0 | 4.0 | 3.0 | 5.2 |
| cross_device_strong | attack | 184 | 407 | 139 | 86 | 0.755435 | 0.467391 | 45.0 | 2.0 | 2.0 | 2.0 | 3.5 |
| cross_device_weak_guest | attack | 101 | 274 | 21 | 1 | 0.207921 | 0.009901 | 80.0 | 4.0 | 6.0 | 3.0 | 3.0 |
| fast_burst_v2 | attack | 29 | 330 | 28 | 21 | 0.965517 | 0.724138 | 1.0 | 5.0 | 6.0 | 9.0 | 11.0 |
| merchant_normal_amount_attack | attack | 30 | 275 | 29 | 19 | 0.966667 | 0.633333 | 1.0 | 4.0 | 5.2 | 7.0 | 9.0 |
| mixed_campaign_behavior | attack | 24 | 268 | 21 | 15 | 0.875 | 0.625 | 3.0 | 5.0 | 8.0 | 9.0 | 10.0 |
| patient_tester_v2 | attack | 46 | 160 | 41 | 13 | 0.891304 | 0.282609 | 5.0 | 2.0 | 2.0 | 3.0 | 4.0 |
| session_churn_v2 | attack | 27 | 284 | 25 | 20 | 0.925926 | 0.740741 | 2.0 | 4.0 | 5.0 | 7.0 | 9.0 |
| sparse_multiday_v2 | attack | 69 | 185 | 60 | 11 | 0.869565 | 0.15942 | 9.0 | 2.0 | 2.0 | 3.0 | 4.0 |
| success_camouflage_v2 | attack | 28 | 304 | 28 | 19 | 1.0 | 0.678571 | 0.0 | 5.0 | 7.0 | 9.0 | 11.0 |
| ultra_patient_v2 | attack | 45 | 141 | 39 | 4 | 0.866667 | 0.088889 | 6.0 | 2.0 | 2.0 | 5.5 | 6.7 |
| variable_cadence_v2 | attack | 29 | 313 | 29 | 26 | 1.0 | 0.896552 | 0.0 | 4.0 | 5.2 | 5.0 | 7.5 |
| warm_up_then_attack_v2 | attack | 31 | 393 | 27 | 11 | 0.870968 | 0.354839 | 4.0 | 10.0 | 13.4 | 12.0 | 16.0 |

## 11. Patient result

{"block_rate": 0.282609, "blocked_devices": 13, "cumulative": {"1": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.0, "reviewed_devices": 0}, "2": {"block_rate": 0.021739, "blocked_devices": 1, "review_or_higher_rate": 0.847826, "reviewed_devices": 39}, "3": {"block_rate": 0.217391, "blocked_devices": 10, "review_or_higher_rate": 0.891304, "reviewed_devices": 41}, "5": {"block_rate": 0.282609, "blocked_devices": 13, "review_or_higher_rate": 0.891304, "reviewed_devices": 41}}, "devices": 46, "median_first_block_attempt": 3.0, "median_first_review_attempt": 2.0, "never_detected_devices": 5, "p90_first_block_attempt": 4.0, "p90_first_review_attempt": 2.0, "review_or_higher_rate": 0.891304, "reviewed_devices": 41, "scenarios": ["patient_tester_v2"]}

## 12. Ultra-patient result

{"block_rate": 0.088889, "blocked_devices": 4, "cumulative": {"1": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.0, "reviewed_devices": 0}, "2": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.844444, "reviewed_devices": 38}, "3": {"block_rate": 0.022222, "blocked_devices": 1, "review_or_higher_rate": 0.866667, "reviewed_devices": 39}, "5": {"block_rate": 0.044444, "blocked_devices": 2, "review_or_higher_rate": 0.866667, "reviewed_devices": 39}}, "devices": 45, "median_first_block_attempt": 5.5, "median_first_review_attempt": 2.0, "never_detected_devices": 6, "p90_first_block_attempt": 6.7, "p90_first_review_attempt": 2.0, "review_or_higher_rate": 0.866667, "reviewed_devices": 39, "scenarios": ["ultra_patient_v2"]}

## 13. Sparse-multiday result

{"block_rate": 0.15942, "blocked_devices": 11, "cumulative": {"1": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.0, "reviewed_devices": 0}, "2": {"block_rate": 0.014493, "blocked_devices": 1, "review_or_higher_rate": 0.84058, "reviewed_devices": 58}, "3": {"block_rate": 0.101449, "blocked_devices": 7, "review_or_higher_rate": 0.869565, "reviewed_devices": 60}, "5": {"block_rate": 0.144928, "blocked_devices": 10, "review_or_higher_rate": 0.869565, "reviewed_devices": 60}}, "devices": 69, "median_first_block_attempt": 3.0, "median_first_review_attempt": 2.0, "never_detected_devices": 9, "p90_first_block_attempt": 4.0, "p90_first_review_attempt": 2.0, "review_or_higher_rate": 0.869565, "reviewed_devices": 60, "scenarios": ["sparse_multiday_v2"]}

Long-horizon usefulness is interpreted from the frozen scores/features only:
useful under the frozen system

## 14. Cross-device strong result

{"block_rate": 0.467391, "blocked_devices": 86, "cumulative": {"1": {"block_rate": 0.005435, "blocked_devices": 1, "review_or_higher_rate": 0.081522, "reviewed_devices": 15}, "2": {"block_rate": 0.309783, "blocked_devices": 57, "review_or_higher_rate": 0.695652, "reviewed_devices": 128}, "3": {"block_rate": 0.418478, "blocked_devices": 77, "review_or_higher_rate": 0.744565, "reviewed_devices": 137}, "5": {"block_rate": 0.467391, "blocked_devices": 86, "review_or_higher_rate": 0.755435, "reviewed_devices": 139}}, "devices": 184, "median_first_block_attempt": 2.0, "median_first_review_attempt": 2.0, "never_detected_devices": 45, "p90_first_block_attempt": 3.5, "p90_first_review_attempt": 2.0, "review_or_higher_rate": 0.755435, "reviewed_devices": 139, "scenarios": ["cross_device_strong"]}

## 15. Cross-device partial result

{"block_rate": 0.037594, "blocked_devices": 5, "cumulative": {"1": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.007519, "reviewed_devices": 1}, "2": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.12782, "reviewed_devices": 17}, "3": {"block_rate": 0.022556, "blocked_devices": 3, "review_or_higher_rate": 0.293233, "reviewed_devices": 39}, "5": {"block_rate": 0.030075, "blocked_devices": 4, "review_or_higher_rate": 0.406015, "reviewed_devices": 54}}, "devices": 133, "median_first_block_attempt": 3.0, "median_first_review_attempt": 3.0, "never_detected_devices": 79, "p90_first_block_attempt": 5.2, "p90_first_review_attempt": 4.0, "review_or_higher_rate": 0.406015, "reviewed_devices": 54, "scenarios": ["cross_device_partial"]}

## 16. Cross-device weak-guest result

{"block_rate": 0.009901, "blocked_devices": 1, "cumulative": {"1": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.0, "reviewed_devices": 0}, "2": {"block_rate": 0.0, "blocked_devices": 0, "review_or_higher_rate": 0.029703, "reviewed_devices": 3}, "3": {"block_rate": 0.009901, "blocked_devices": 1, "review_or_higher_rate": 0.059406, "reviewed_devices": 6}, "5": {"block_rate": 0.009901, "blocked_devices": 1, "review_or_higher_rate": 0.168317, "reviewed_devices": 17}}, "devices": 101, "median_first_block_attempt": 3.0, "median_first_review_attempt": 4.0, "never_detected_devices": 80, "p90_first_block_attempt": 3.0, "p90_first_review_attempt": 6.0, "review_or_higher_rate": 0.207921, "reviewed_devices": 21, "scenarios": ["cross_device_weak_guest"]}

The combined cross-device delay is {"block_rate": 0.220096, "blocked_devices": 92, "cumulative": {"1": {"block_rate": 0.002392, "blocked_devices": 1, "review_or_higher_rate": 0.038278, "reviewed_devices": 16}, "2": {"block_rate": 0.136364, "blocked_devices": 57, "review_or_higher_rate": 0.354067, "reviewed_devices": 148}, "3": {"block_rate": 0.19378, "blocked_devices": 81, "review_or_higher_rate": 0.435407, "reviewed_devices": 182}, "5": {"block_rate": 0.217703, "blocked_devices": 91, "review_or_higher_rate": 0.502392, "reviewed_devices": 210}}, "devices": 418, "median_first_block_attempt": 2.0, "median_first_review_attempt": 2.0, "never_detected_devices": 204, "p90_first_block_attempt": 4.0, "p90_first_review_attempt": 4.0, "review_or_higher_rate": 0.511962, "reviewed_devices": 214, "scenarios": ["cross_device_strong", "cross_device_partial", "cross_device_weak_guest"]}.

## 17. All legitimate-family friction

| scenario | population | devices | requests | reviewed_devices | blocked_devices | review_or_higher_rate | block_rate | never_detected_devices | median_first_review_attempt | p90_first_review_attempt | median_first_block_attempt | p90_first_block_attempt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| campaign_rush_v2 | legitimate | 153 | 580 | 13 | 0 | 0.084967 | 0.0 |  | 4.0 | 5.8 |  |  |
| campus_office_shared_network | legitimate | 351 | 747 | 9 | 0 | 0.025641 | 0.0 |  | 5.0 | 5.2 |  |  |
| dormant_returning_customer_v2 | legitimate | 166 | 924 | 0 | 0 | 0.0 | 0.0 |  |  |  |  |  |
| high_value_retry_v2 | legitimate | 120 | 417 | 54 | 8 | 0.45 | 0.066667 |  | 3.0 | 4.0 | 3.0 | 4.3 |
| household_shared_ip | legitimate | 410 | 527 | 5 | 0 | 0.012195 | 0.0 |  | 2.0 | 3.0 |  |  |
| micro_payment_regular | legitimate | 178 | 816 | 22 | 1 | 0.123596 | 0.005618 |  | 5.0 | 6.0 | 6.0 | 6.0 |
| mobile_network_churn_v2 | legitimate | 164 | 685 | 30 | 2 | 0.182927 | 0.012195 |  | 4.0 | 5.0 | 5.0 | 5.8 |
| multi_device_customer_v2 | legitimate | 616 | 1163 | 42 | 0 | 0.068182 | 0.0 |  | 2.0 | 4.0 |  |  |
| network_retry_storm_v2 | legitimate | 116 | 811 | 88 | 25 | 0.758621 | 0.215517 |  | 5.0 | 7.0 | 9.0 | 9.6 |
| new_guest_checkout | legitimate | 411 | 605 | 0 | 0 | 0.0 | 0.0 |  |  |  |  |  |
| persistent_card_problem_v2 | legitimate | 100 | 676 | 86 | 34 | 0.86 | 0.34 |  | 4.0 | 6.0 | 7.0 | 8.0 |
| returning_long_history | legitimate | 287 | 1982 | 1 | 0 | 0.003484 | 0.0 |  | 6.0 | 6.0 |  |  |
| subscription_dunning_v2 | legitimate | 128 | 1435 | 127 | 93 | 0.992188 | 0.726562 |  | 7.0 | 9.0 | 8.0 | 11.0 |

## 18. Subscription-dunning result

{"allow_device_rate": 0.007812, "block_rate": 0.726562, "blocked_devices": 93, "customer_id_absent_requests": 321, "customer_id_present_requests": 1114, "devices": 128, "devices_with_historical_success_in_30d": 112, "requests": 1435, "review_or_higher_rate": 0.992188, "reviewed_devices": 127}

## 19. Guest versus logged-in result

{"device_segments": [{"attack_block_rate": 0.031646, "attack_devices": 158, "attack_review_or_higher_rate": 0.322785, "devices": 912, "legitimate_block_rate": 0.0, "legitimate_devices": 754, "legitimate_review_or_higher_rate": 0.007958, "segment": "always_guest"}, {"attack_block_rate": 0.417445, "attack_devices": 642, "attack_review_or_higher_rate": 0.799065, "devices": 3088, "legitimate_block_rate": 0.066639, "legitimate_devices": 2446, "legitimate_review_or_higher_rate": 0.192559, "segment": "ever_customer_present"}], "request_segments": [{"allow_requests": 4219, "block_requests": 453, "devices": 2721, "model_metrics": {"brier": 0.171575, "ece": 0.138176, "log_loss": 0.566837, "positive_rate": 0.22455, "pr_auc": 0.491878, "roc_auc": 0.704461}, "requests": 5565, "review_requests": 893, "segment": "customer_absent"}, {"allow_requests": 7625, "block_requests": 869, "devices": 3088, "model_metrics": {"brier": 0.157503, "ece": 0.125567, "log_loss": 0.504091, "positive_rate": 0.207902, "pr_auc": 0.510085, "roc_auc": 0.767346}, "requests": 9799, "review_requests": 1305, "segment": "customer_present"}]}

Guest legitimate users are interpreted as: not disproportionately penalized by more than one percentage point

## 20. Evidence-gate value

{"attacks_no_longer_blocked": 116, "attempts_at_or_above_block_threshold": 1879, "attempts_withheld_low_evidence": 557, "attempts_withheld_trusted": 0, "block_attempts_suppressed_by_gate": 557, "devices_blocked_with_gate": 436, "devices_blocked_without_gate": 595, "devices_suppressed_by_gate": 159, "evidence_qualified_block_attempts": 1322, "legitimate_blocks_prevented": 43, "score_only_block_candidate_attempts": 1879, "withheld_attack_scenarios": {"cross_device_strong": 3, "patient_tester_v2": 28, "sparse_multiday_v2": 49, "ultra_patient_v2": 35, "variable_cadence_v2": 1}, "withheld_legitimate_scenarios": {"high_value_retry_v2": 7, "mobile_network_churn_v2": 1, "network_retry_storm_v2": 1, "subscription_dunning_v2": 34}}

## 21. Detection-delay results

{"block_rate": 0.34125, "blocked_devices": 273, "cumulative": {"1": {"block_rate": 0.00125, "blocked_devices": 1, "review_or_higher_rate": 0.02, "reviewed_devices": 16}, "2": {"block_rate": 0.07375, "blocked_devices": 59, "review_or_higher_rate": 0.365, "reviewed_devices": 292}, "3": {"block_rate": 0.12875, "blocked_devices": 103, "review_or_higher_rate": 0.43125, "reviewed_devices": 345}, "5": {"block_rate": 0.17875, "blocked_devices": 143, "review_or_higher_rate": 0.61625, "reviewed_devices": 493}}, "devices": 800, "median_first_block_attempt": 5.0, "median_first_review_attempt": 2.0, "never_detected_devices": 236, "p90_first_block_attempt": 10.0, "p90_first_review_attempt": 6.0, "review_or_higher_rate": 0.705, "reviewed_devices": 564, "scenarios": ["burst_pause_burst_v2", "cross_device_partial", "cross_device_strong", "cross_device_weak_guest", "fast_burst_v2", "merchant_normal_amount_attack", "mixed_campaign_behavior", "patient_tester_v2", "session_churn_v2", "sparse_multiday_v2", "success_camouflage_v2", "ultra_patient_v2", "variable_cadence_v2", "warm_up_then_attack_v2"]}

The same fixed attempt cuts are recorded for patient, ultra-patient, sparse, and
combined cross-device cohorts in the detection-delay artifact.

## 22. Fixed baseline comparisons

The full predeclared grid and nearest of the eight fixed Model v2 thresholds:

| baseline | baseline_family | baseline_recall | baseline_fpr | model_fixed_threshold | model_recall | model_fpr | fpr_gap | recall_difference |
|---|---|---|---|---|---|---|---|---|
| count_requests_5m_ge_2 | request_count | 0.215 | 0.1216 | 0.8 | 0.67875 | 0.12875 | 0.00715 | 0.46375 |
| count_requests_5m_ge_3 | request_count | 0.0938 | 0.0372 | 0.9 | 0.48625 | 0.064375 | 0.027175 | 0.39245 |
| count_requests_5m_ge_4 | request_count | 0.0663 | 0.0122 | 0.9 | 0.48625 | 0.064375 | 0.052175 | 0.41995 |
| count_requests_5m_ge_5 | request_count | 0.0488 | 0.0019 | 0.9 | 0.48625 | 0.064375 | 0.062475 | 0.43745 |
| count_requests_5m_ge_6 | request_count | 0.0325 | 0.0 | 0.9 | 0.48625 | 0.064375 | 0.064375 | 0.45375 |
| count_requests_24h_ge_3 | request_count | 0.4688 | 0.3403 | 0.3 | 0.85 | 0.358438 | 0.018138 | 0.3812 |
| count_requests_24h_ge_4 | request_count | 0.3575 | 0.2016 | 0.6 | 0.76375 | 0.2025 | 0.0009 | 0.40625 |
| count_requests_24h_ge_5 | request_count | 0.3063 | 0.1434 | 0.75 | 0.705 | 0.149062 | 0.005662 | 0.3987 |
| count_requests_24h_ge_6 | request_count | 0.2675 | 0.0878 | 0.9 | 0.48625 | 0.064375 | -0.023425 | 0.21875 |
| count_requests_24h_ge_8 | request_count | 0.1925 | 0.0291 | 0.9 | 0.48625 | 0.064375 | 0.035275 | 0.29375 |
| failures_7d_ge_1 | long_horizon_count | 0.7375 | 0.3272 | 0.3 | 0.85 | 0.358438 | 0.031238 | 0.1125 |
| failures_7d_ge_2 | long_horizon_count | 0.44 | 0.1512 | 0.75 | 0.705 | 0.149062 | -0.002138 | 0.265 |
| failures_7d_ge_3 | long_horizon_count | 0.3312 | 0.0847 | 0.9 | 0.48625 | 0.064375 | -0.020325 | 0.15505 |
| failures_7d_ge_4 | long_horizon_count | 0.2587 | 0.045 | 0.9 | 0.48625 | 0.064375 | 0.019375 | 0.22755 |
| failures_7d_ge_6 | long_horizon_count | 0.1688 | 0.0203 | 0.9 | 0.48625 | 0.064375 | 0.044075 | 0.31745 |
| customer_devices_7d_ge_2 | cross_device_count | 0.3425 | 0.1834 | 0.7 | 0.72375 | 0.166563 | -0.016837 | 0.38125 |
| customer_devices_7d_ge_3 | cross_device_count | 0.2562 | 0.0966 | 0.8 | 0.67875 | 0.12875 | 0.03215 | 0.42255 |
| customer_devices_7d_ge_4 | cross_device_count | 0.2037 | 0.0284 | 0.9 | 0.48625 | 0.064375 | 0.035975 | 0.28255 |
| rules_ge_2 | rules_only | 0.2675 | 0.0872 | 0.9 | 0.48625 | 0.064375 | -0.022825 | 0.21875 |
| rules_ge_3 | rules_only | 0.1537 | 0.0344 | 0.9 | 0.48625 | 0.064375 | 0.029975 | 0.33255 |
| rules_ge_4 | rules_only | 0.0775 | 0.0175 | 0.9 | 0.48625 | 0.064375 | 0.046875 | 0.40875 |
| rules_ge_5 | rules_only | 0.0325 | 0.0019 | 0.9 | 0.48625 | 0.064375 | 0.062475 | 0.45375 |
| rules_ge_6 | rules_only | 0.02 | 0.0 | 0.9 | 0.48625 | 0.064375 | 0.064375 | 0.46625 |

No baseline or model threshold was optimized on Blind v2.

## 23. Development-to-blind generalization gap

{"attack_block": -0.25065, "attack_review_or_higher": -0.1689, "brier": 0.077767, "ece": 0.099018, "legitimate_block": 0.042037, "legitimate_review_or_higher": 0.096062, "pr_auc": -0.291126, "roc_auc": -0.169021}

Absolute deltas are Blind v2 minus Dataset v3 validation.

## 24. Historical Blind v1.1 context

Old Blind v1.1 was approximately PR-AUC 0.5875, ROC-AUC 0.8262, attack REVIEW+
66.2%, attack BLOCK 44.0%, legitimate REVIEW+ 6.5%, and legitimate BLOCK 1.3%.
Blind v1.1 and v2 are different benchmarks; these are directional engineering
context, not a controlled performance-gain claim.

## 25. Distribution-shift interpretation

Blind v2 median PSI was 0.0792, with larger shifts in device age (0.9358),
customer age (0.5285), active days (0.4269), gap variability (0.3542), and amount
(0.2887). Performance changes reflect a mixture of merchant/composition/temporal
shift and model generalization; not every delta is attributable to model quality.

## 26. Legitimate-decline warning

Blind v2's legitimate decline rate is 34.49%, above the predeclared 34% warning
level but below the 46% hard-fail gate. The benchmark is friction-heavy and was
not invalidated or regenerated.

## 27. Artifact hashes

{"baseline_report": "efc07a047039c5eba1073582fcc49e93f46638f8014b4c4a0fc23199f4ba40b5", "calibration": "4a433e60951b2095198eeaeed865c2fa2d2659c6e480dcd39ddea5fe4f8e7629", "consumption_record": "96b6265657c9c2273d2b25938a0377a47a36a2f0487174c01f514b439aae8903", "detection_delay": "d1e9e02c7f38c01049f1db3e212fe57e1d00cd2eaf12b2be786df2bc664281df", "evaluation_module": "4b39bf139be61201d5e4f4900a8ebffb50f7cb6d1269f2f875694711911a8c44", "evaluation_pipeline": "5238c301b23c727088bff8d9e996a8ed7b0e426eac4da2187b9f0d91c8be8f9a", "family_metrics": "c0c4238aa15e9a06f92bdb5f0585c9d05bc751099c6ac8208430dea2ef152e23", "metrics": "8624f6f3f1755b26bfc7e732857ced4b8d8ee33e9cf217d79ad6fba63f4331b1", "threshold_table": "94aabaf86308b0e72fd68a180082bd1376bbd845ec5a26b44691f1ca330c4815"}

## 28. Preservation checks

Post-evaluation verification preserved Blind v2 source/data bytes, Blind v1.1,
Dataset v3, Feature Contract/Engine v2, Model v2, and Policy v2. Only the
authoritative Blind v2 lifecycle fields and new Phase 13 artifacts changed.

## 29. Tests and lint

Pre-score preflight and Phase 13 tests passed before the one look. Final test and
lint outcomes are recorded in the handoff and result-hash manifest; no frontend
files changed.

## 30. Remaining weaknesses

aggregate legitimate REVIEW+ exceeds 6%; aggregate legitimate BLOCK exceeds 1%; subscription dunning has elevated friction.

## 31. Final verdict

**WEAK synthetic generalization.** core attack-review coverage or the 2% legitimate-block ceiling failed.

This verdict applies to the frozen synthetic benchmark, not production prevalence
or a claim of issuer/network fraud prevention.

## 32. Final lifecycle confirmation

```text
Blind v2 evaluated = true
Blind v2 consumed = true
Model v2 frozen = true
Policy v2 frozen = true
post-blind tuning = false
```

Phase 13 stops here. No retraining, retuning, regeneration, runtime switch,
cleanup, UI work, or deployment was performed.
