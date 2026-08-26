# Phase 2B policy diagnosis for Phase 2C

This is read-only diagnosis of existing Phase 2B evidence, not threshold tuning.

- Closest ML-only excess: {'candidate_id': 'policy_032', 'total_excess_devices': 58, 'failed_constraints': ['normal_bad_luck:review_excess=47_devices', 'normal_bad_luck:block_excess=2_devices', 'overall_legitimate:review_excess=9_devices']}
- Closest combined excess: {'candidate_id': 'policy_071', 'total_excess_devices': 90, 'failed_constraints': ['flash_hard_retry:review_excess=11_devices', 'normal_bad_luck:review_excess=51_devices', 'overall_legitimate:review_excess=28_devices']}
- Hard-negative high-score evidence: {'definition': 'hard-negative device with allow-all maximum calibrated score at or above the already-frozen Phase 2B minimum ML review threshold 0.35', 'devices': 142, 'one_isolated_high_score': 105, 'consecutive_high_scores': 31, 'multiple_sessions': 25, 'card_switching': 67, 'ip_rotation': 13, 'no_successful_checkout_history': 124}
- Device-level persistence comparison: {'maximum_score_device_roc_auc': 0.9995117647058823, 'mean_score_device_roc_auc': 0.9997156862745098, 'high_score_count_device_roc_auc': 0.9991401960784313, 'maximum_consecutive_high_device_roc_auc': 0.9992882352941176}
- Checkout-history comparison: {'absent': {'devices': 1501, 'high_maximum_score_devices': 139, 'high_maximum_score_rate': 0.09260493004663557, 'median_maximum_score': 0.028783095907959022}, 'available': {'devices': 199, 'high_maximum_score_devices': 23, 'high_maximum_score_rate': 0.11557788944723618, 'median_maximum_score': 0.028783095907959022}}
- Campaign comparison: {'False': {'devices': 1109, 'high_maximum_score_rate': 0.07484220018034266, 'median_maximum_score': 0.028783095907959022}, 'True': {'devices': 591, 'high_maximum_score_rate': 0.13367174280879865, 'median_maximum_score': 0.01939339042970994}}

Policy hypotheses carried forward: repeated risk, corroborating causal card/IP/
session evidence, decaying accumulation, successful-checkout protection, and
campaign-aware evidence requirements. Scenario labels are not live inputs.
