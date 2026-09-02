# Card-Testing Sentinel — Phase 2.6 Handoff Document

**Phase 2.6 Status:** READY FOR PRE-PBRSS FREEZE
**Date:** September 2026
**Author:** Antigravity (ML & Evaluation Architect)
**Target Recipient:** Phase 3 Evaluation Pipeline

---

## 1. Frozen Baseline Inventory

All artifacts and configurations required for the pre-PBRSS freeze are locked:

| Component | Path | Specification / Version | SHA-256 Digest | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Active Runtime** | `configs/runtime.yaml` | `frozen-v2-runtime` | Committed configuration | Byte-Frozen |
| **Model v2 Artifact** | `artifacts/model_v2/risk_model_v2.joblib` | `model-v2` | `0317cef5d310bc5d5d2ed55e755d995a34c54ad28df5ea780a36cb1e6fea2e3c` | Byte-Frozen |
| **Policy v2 Config** | `configs/policy_v2.yaml` | `validation-selected-v2` | `92b0173e0ba073a9a20b7f09e5d0d82c9d40a52598cb9140ede36714a03c0052` | Unchanged |
| **Dataset v4.1 Raw Events** | `data/generated/development_v4_1/raw_events.csv` | `development-v4.1` | `9024c24fafa9dbd214781e897acbf134d3ab5dbf8ae3d1ffebb45fcce10ae1df` | Byte-Frozen |
| **Dataset v4.1 Labels** | `data/generated/development_v4_1/labels.csv` | `development-v4.1` | `e0613eaba2ee792fbe4e70f0e8a4f5c1ac369cb8fa42902c3c266a029141b81e` | Byte-Frozen |
| **Dataset v4.1 Features** | `data/generated/development_v4_1/features_v3_1.csv` | `merchant-visible-causal-3.1` | `882c4c70a292f0363939107bb3fa8d3f88c50530c0734fd7f6070b76a7859d2e` | Byte-Frozen |
| **Dataset v4.1 Manifest** | `data/generated/development_v4_1/manifest.json` | `development-v4.1` | `9598be1c8f942a3a4bac4d713298506186620a3267a9d1d8b2541e42ce34071e` | Byte-Frozen |
| **Feature Contract v3.1** | `configs/features_v3_1.yaml` | `merchant-visible-causal-3.1` (44 features) | `9f07a99cb2717c361331ab8c6d26df9b28098366b0d9cc25108ed897baeeff4d` | Byte-Frozen |
| **Model v3.1 Artifact** | `artifacts/model_v3_1/risk_model_v3_1.joblib` | `model-v3.1` (`hist_gb_2` + Sigmoid) | Serialized artifact | Frozen |
| **Model v3.1 Metadata** | `artifacts/model_v3_1/metadata.json` | `model-v3.1` | Serialized metadata | Frozen |
| **Model v3.1 Contract** | `artifacts/model_v3_1/feature_contract.json` | `merchant-visible-causal-3.1` | `af66f693eee5043f0e97dfef1c31b1773ae480e38228f47612575d336abe2ce0` | Frozen |
| **Stress Suite (PBRSS-v1)**| `data/generated/post_blind_stress_v1/` | Unconsumed / Not scored | N/A | **UNTOUCHED** |

---

## 2. Integrity of Historical State

- **Blind v2 Evaluation:** Strictly historical and immutable (`artifacts/evaluation/blind_v2_consumption.json`, `artifacts/evaluation/blind_v2_metrics.json`). The recorded verdict remains `WEAK` synthetic generalization.
- **Model v2 Runtime:** The production server runtime in `src/card_testing_sentinel/` continues to evaluate incoming requests against Model v2 and Feature Contract v2.
- **Release Verification:** Verified cleanly via `python scripts/verify_release.py`.

---

## 3. Pre-Requisites for Phase 3 Commencement

Phase 3 (Post-Blind Remediation Stress Suite v1 evaluation) may begin **ONLY AFTER** all the following conditions are met:
1. All Phase 2.6 evidence documentation checks pass.
2. Reproducible README figures are generated in `docs/figures/` and certified by `readme_chart_manifest.json`.
3. The full local test suite passes (`pytest -q`).
4. The release verifier passes (`python scripts/verify_release.py`).
5. A git freeze commit/checkpoint of the Phase 2.6 state exists.

---

## 4. Strict Behavioral Prohibitions for Phase 3

During Phase 3 execution:
- **DO NOT** perform further model training, retraining, or architecture search.
- **DO NOT** tune classification, review, or block thresholds against PBRSS-v1.
- **DO NOT** prune or add features to Feature Contract v3.1.
- **DO NOT** tune, re-weight, or modify the dataset generator.
- **DO NOT** inspect individual PBRSS-v1 rows or iterate on the model after stress scoring.
- **PBRSS-v1 is a single-shot out-of-distribution evaluation.** Its score must be reported honestly without post-hoc remediation iterations.
