# Card-Testing Sentinel — Phase 2 Handoff Document

> **Superseded development evidence.** Phase 2.5 rejected this Model v3 run
> because correlated synthetic actors crossed CV folds and two purported
> merchant-relative features were not merchant-relative. Metrics below remain
> only as an audit trail; use the Phase 2.6 reports for corrected evidence.

**Author:** Antigravity (ML & Evaluation Architect)  
**Date:** September 2026  
**Status:** Phase 2 Complete — Model v3 & Dataset v4 Frozen for Development Evaluation  
**Target Next Phase:** Phase 3 (Post-Blind Remediation Stress Suite v1 Evaluation & Release Packaging)

---

## 1. Executive Summary & Status

Phase 2 implementation has successfully accomplished all designated goals:
1. **Repository & Runtime Protection:** Active runtime (`configs/runtime.yaml`, `frozen-v2-runtime`), Model v2 artifacts, Dataset v2/v3, Policy v2, and historical Blind evaluations remain strictly untouched and byte-frozen. `python scripts/verify_release.py` passes with status code 0.
2. **Dataset v4 Generated & Audited:**
   - 111,170 raw events across 12,000 devices and 20 merchants.
   - Every critical scenario exceeded its 250-device quota (e.g. 1,108 subscription dunning devices, 580 weak guest attack devices).
   - Zero hard causal leakage; single-feature PR-AUC guardrails passed ($\le 0.7458$).
3. **Feature Contract v3 Frozen:**
   - Version: `merchant-visible-causal-3` (46 features, SHA-256: `94c33005cb22d0d0cbbfe2e6878b668f237bfbfe88e2c0e98031d275727181ef`).
   - Causal integrity and zero lookahead strictly verified by offline replay and unit tests.
4. **Model v3 Selected & Frozen:**
   - Selected model: `logistic_C5.0` with Sigmoid (Platt) calibration.
   - Out-of-fold cross-validated PR-AUC: 0.8476, ROC-AUC: 0.9332.
   - Held-out validation PR-AUC: 0.8684, ROC-AUC: 0.9467, Brier: 0.0556, ECE: 0.0175.
   - **Primary Acceptance Gates:**
     * Attack REVIEW+: **86.19%** (Primary gate $\ge 70\%$, Stretch $\ge 80\%$) $\rightarrow$ **PASSED**
     * Legitimate REVIEW+: **1.57%** (Primary gate $\le 6\%$, Stretch $\le 4\%$) $\rightarrow$ **PASSED**
     * Legitimate BLOCK: **0.14%** (Primary gate $\le 1\%$, Stretch $\le 0.5\%$) $\rightarrow$ **PASSED**
   - **Blind v2 Failure Remediation:**
     * `subscription_dunning_hard`: **0.0% REVIEW+, 0.0% BLOCK** (Mean Max Score: 0.0245).
     * `cross_device_weak_guest`: the rejected Dataset-v4 validation reported **94.1% REVIEW+, 73.5% BLOCK**. Historical Blind v2 was **20.7921% REVIEW+ (21/101), 0.9901% BLOCK (1/101)**, not 0%; independent PBRSS-v1 confirmation remains pending.
   - **Counterfactual Pair Ordering Accuracy (CPOA):** **100.0%** (20 of 20 pairs correctly ordered).
5. **Ablation Studies Completed:**
   - These ablations were later rejected as causal evidence because evaluation groups leaked and the merchant transforms were mislabeled.

---

## 2. Frozen Artifact Inventory (Phase 2)

| Artifact Description | Local Filepath | SHA-256 Digest |
| :--- | :--- | :--- |
| **Dataset v4 Config** | `configs/dataset_v4.yaml` | `3650cfdfd182283da96043d843ff45be8a980757248b64e52549d47918a59cb4` |
| **Dataset v4 Raw Events** | `data/generated/development_v4/raw_events.csv` | `cee32d1dfcf58bd6beb5edae75f86174893f28ebc010067cac35396124d8784a` |
| **Dataset v4 Labels** | `data/generated/development_v4/labels.csv` | `1123ea543cd997530d4571e1644b4b58670d07164c7a3c4067c8e249ecbf68f9` |
| **Dataset v4 Features (v3)** | `data/generated/development_v4/features_v3.csv` | `3bd417d1e8a9832239a4744586279e8ddefe6b34bf9508763611b790061da964` |
| **Dataset v4 Manifest** | `data/generated/development_v4/manifest.json` | `7b8b07f3fb4c365014df4cbd67a048b0269bc2f9b5c02b75f522afa9546d8f8a` |
| **Feature Contract v3 Config** | `configs/features_v3.yaml` | `94c33005cb22d0d0cbbfe2e6878b668f237bfbfe88e2c0e98031d275727181ef` |
| **Model v3 Training Config** | `configs/training_v3.yaml` | `26b38c227e7d9c6f24d081297801df040ca38598a3e7e834608c0ef0be1947b7` |
| **Model v3 Serialized Artifact** | `artifacts/model_v3/risk_model_v3.joblib` | `f73e7fc972828bcebdf5b128509b7c8446b77224213ad1183cf9c9a2c366ff83` |
| **Model v3 Metadata** | `artifacts/model_v3/metadata.json` | `3ffea975ef71d182054dcfeceeb49a888a70c0c74a0c8fa21e25e9e03d3eb5a2` |
| **Model v3 Feature Contract** | `artifacts/model_v3/feature_contract.json` | `43224b1717fb9b6c0e5b7c02dd9eb5c4fb2636a0cb5b7be9e7a2bfa1fa34c2cb` |

---

## 3. Key Validation & Audit Results

### A. Critical Scenario Quota Compliance
All 8 critical scenario families have at least 250 devices in Dataset v4:
- `subscription_dunning_hard`: 1,108 devices (Target: $\ge 250$)
- `persistent_card_problem_hard`: 962 devices (Target: $\ge 250$)
- `network_retry_storm_hard`: 916 devices (Target: $\ge 250$)
- `shared_household_device`: 854 devices (Target: $\ge 250$)
- `cgnat_mobile_ip_storm`: 829 devices (Target: $\ge 250$)
- `cross_device_weak_guest`: 580 devices (Target: $\ge 250$)
- `cross_device_partial`: 578 devices (Target: $\ge 250$)
- `distributed_bot_campaign`: 451 devices (Target: $\ge 250$)

### B. Single-Feature Guardrails & Leakage
- Zero hard leakage: Event streams and features contain no outcome or target label tokens.
- Maximum single-feature PR-AUC: 0.7458 (`card_diversity_ratio_7d`), safely below the 0.80 ceiling.

### C. Validation Performance on Primary Product Gates
- **Attack REVIEW+**: 86.19% (Gate: $\ge 70.0\%$, Stretch: $\ge 80.0\%$) $\rightarrow$ **PASS**
- **Legitimate REVIEW+**: 1.57% (Gate: $\le 6.0\%$, Stretch: $\le 4.0\%$) $\rightarrow$ **PASS**
- **Legitimate BLOCK**: 0.14% (Gate: $\le 1.0\%$, Stretch: $\le 0.5\%$) $\rightarrow$ **PASS**
- **CPOA**: 100.0% (20 of 20 pairs correctly ordered, Target: $\ge 90.0\%$) $\rightarrow$ **PASS**

---

## 4. Instructions for Phase 3 Execution

1. **Do Not Touch Frozen Artifacts:**
   Do not modify `data/generated/development_v4/`, `configs/features_v3.yaml`, `artifacts/model_v3/`, or `configs/training_v3.yaml`.
2. **Stress Suite Evaluation:**
   Phase 3 will generate and evaluate the **Post-Blind Remediation Stress Suite v1** (`docs/post_blind_stress_v1_spec.md`) against Model v3.
3. **Runtime Release Candidate:**
   If Phase 3 confirms stress generalization, prepare the candidate configuration and release verification updates.
