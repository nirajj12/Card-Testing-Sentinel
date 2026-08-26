# V2 development data-quality report

Status: **passed**

- blind_test_absent: PASS — train/validation only
- split_values: PASS — ['train', 'validation']
- device_split_overlap: PASS — 0
- manifest_hashes: PASS — {'raw_events.csv': '9232c7049916cb638d7eedd3faf922b1569c38d74850df100eb98622ab73614f', 'events_with_features.csv': '9fd1a9eabfa73a65362c93fa7f0595f9987bd274b324edf53b922984a076e3e4', 'device_splits.csv': 'c14524c2c601237e969edeb1b36edb3f67e9aabea1f875e5e1daf361181feefe'}
- configuration_hashes: PASS — {'generation': 'fa57f16bd4260e5ae8917e2c101ae4e96b55ef8b69025d1c0953bb4a88da5f59', 'features': '10d570284bb546a7fe66538f9c5651efa1f14dece6bffa5b9ca94bb1938fb4b7'}
- manifest_counts: PASS — {'devices': 10000, 'events': 61862, 'requests': 26760, 'sessions': 12686, 'train_devices': 8000, 'validation_devices': 2000}
- configured_scenario_counts: PASS — {'attack_burst': 600, 'attack_evasive': 450, 'attack_patient': 450, 'flash_hard_retry': 500, 'flash_standard': 1500, 'normal_bad_luck': 500, 'normal_standard': 6000}
- timestamps: PASS — UTC parse and unique sequence
- deterministic_order: PASS — timestamp then event_sequence
- privacy_fields: PASS — []
- feature_allowlist_leakage: PASS — []
- outcomes_absent_at_precheck: PASS — []
- finite_features: PASS — (26760, 39)
- one_row_per_precheck: PASS — {'features': 26760, 'requests': 26760}
- stable_card_bin: PASS — 16009
- request_outcome_linkage: PASS — 26760
- approval_completion_order: PASS — 8342
- no_legitimate_request_after_completion: PASS — 0
- patient_sessions_separate_days: PASS — {'count': 450.0, 'mean': 3.082222222222222, 'std': 0.8362044082774663, 'min': 2.0, '25%': 2.0, '50%': 3.0, '75%': 4.0, 'max': 4.0}
- returning_normal_sessions_later: PASS — {'multi_session_devices': 979}
- entity_overlap_audit: PASS — {'card_fingerprint': 0, 'ip_fingerprint': 980}
- scenario_outcome_overlap: PASS — {'attack_burst': {'approved': 2913, 'declined': 3611}, 'attack_evasive': {'approved': 1671, 'declined': 2021}, 'attack_patient': {'approved': 1520, 'declined': 1910}, 'flash_hard_retry': {'approved': 524, 'declined': 1322}, 'flash_standard': {'approved': 1636, 'declined': 241}, 'normal_bad_luck': {'approved': 530, 'declined': 1332}, 'normal_standard': {'approved': 6567, 'declined': 962}}
- online_batch_parity: PASS — 26760
- validation_subgroup_support: PASS — {'normal_standard': 1200, 'flash_standard': 300, 'attack_burst': 120, 'normal_bad_luck': 100, 'flash_hard_retry': 100, 'attack_evasive': 90, 'attack_patient': 90}
- training_only_sanity: PASS — {'scope': 'training-only data-quality diagnostic; not V2 model performance', 'evaluation': 'five-fold device-grouped out-of-fold on training devices only', 'baseline_average_precision': 0.9099110669331556, 'baseline_roc_auc': 0.9506126834737354, 'baseline_f1': 0.87831312733582, 'training_only_threshold': 0.45320665442995983, 'folds': [{'fold': 0, 'fit_devices': 6409, 'holdout_devices': 1591, 'device_overlap': 0, 'roc_auc': 0.955029136250942, 'average_precision': 0.9125156890396722, 'f1': 0.8748346092080966}, {'fold': 1, 'fit_devices': 6394, 'holdout_devices': 1606, 'device_overlap': 0, 'roc_auc': 0.9507328362283819, 'average_precision': 0.9098707414711036, 'f1': 0.8847213286190324}, {'fold': 2, 'fit_devices': 6388, 'holdout_devices': 1612, 'device_overlap': 0, 'roc_auc': 0.9474420710262352, 'average_precision': 0.9076205939861014, 'f1': 0.8759732789801757}, {'fold': 3, 'fit_devices': 6402, 'holdout_devices': 1598, 'device_overlap': 0, 'roc_auc': 0.948078551566503, 'average_precision': 0.9080585819423201, 'f1': 0.8816727313416021}, {'fold': 4, 'fit_devices': 6407, 'holdout_devices': 1593, 'device_overlap': 0, 'roc_auc': 0.9531722542386774, 'average_precision': 0.9154040513981351, 'f1': 0.8749641416267533}], 'shuffled_label_roc_auc': 0.4816242145769458, 'shuffled_label_level': 'device', 'shuffled_fold_device_overlap': 0, 'strongest_one_feature': {'feature': 'prior_attempts_7d', 'direction': '>=', 'threshold': 3.0, 'weighted_f1': 0.724063684763532, 'average_precision': 0.7398587252186474}, 'single_feature_search': 'all unique thresholds, both >= and <= directions, device weighted, training only', 'near_constant_features': [], 'high_correlation_pairs': [{'left': 'prior_attempts_10s', 'right': 'prospective_requests_10s', 'absolute_pearson': 0.9860442331285507}, {'left': 'prior_attempts_60s', 'right': 'prospective_requests_60s', 'absolute_pearson': 0.994880944087574}], 'passed': True}
- training_scenario_overlap_table: PASS — {'attack_burst': 480, 'attack_evasive': 360, 'attack_patient': 360, 'flash_hard_retry': 400, 'flash_standard': 1200, 'normal_bad_luck': 400, 'normal_standard': 4800}
- no_deterministic_scenario_range: PASS — []
