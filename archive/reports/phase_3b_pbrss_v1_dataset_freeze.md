# Phase 3B — PBRSS-v1 Authoritative Dataset Freeze

## 1. Phase 3B status

The authoritative PBRSS-v1 dataset was materialized exactly once from the committed corrected machinery and frozen successfully. This report contains structural and integrity evidence only.

## 2. Frozen lineage

- Model v3.1 pre-PBRSS freeze: `1c9dab4ed2902b4207e6758f1c929fee1b8a08dc`
- PBRSS-v1 machinery freeze: `5941689847ed7a44f2db02fc86607dc619e6167c`

## 3. Canonical paths

- Dataset directory: `data/generated/post_blind_stress_v1/`
- Raw lifecycle events: `data/generated/post_blind_stress_v1/raw_events.csv`
- Device labels: `data/generated/post_blind_stress_v1/labels.csv`
- Causal features: `data/generated/post_blind_stress_v1/features_v3_1.csv`
- Dataset manifest: `data/generated/post_blind_stress_v1/manifest.json`
- Freeze manifest: `artifacts/evaluation/pbrss_v1_freeze_manifest.json`

No second authoritative PBRSS copy exists.

## 4. Dataset identity

- Dataset: `post-blind-remediation-stress-suite-v1`
- Specification: `pbrss-v1-frozen-spec`
- Generator: `pbrss-v1-generator-1`
- Seed: `773829104`

## 5. Structural counts

- Events: 52,462
- Authorization requests: 20,714
- Devices: 5,000
- Attack devices: 1,250
- Legitimate devices: 3,750
- Merchants: 16
- Archetypes: 8

The authorization-request target is 20,000 with a frozen allowed range of 18,000–22,000. The observed 20,714 requests pass.

## 6. Exact scenario quotas

- `stealth_low_amount_drip`: 250
- `hybrid_credential_stuffing_probe`: 250
- `mixed_card_probe`: 750
- `charity_micro_donation_spike`: 500
- `b2b_multi_corporate_card`: 250
- `ordinary_checkout`: 3,000

## 7. Merchant isolation and coverage

PBRSS merchant overlap with development-v4.1 is exactly zero. All 16 PBRSS merchants contain both attack and legitimate traffic. The eight archetypes are B2B wholesale, digital micro-payment, donation/charity, ecommerce, flash sale, guest-heavy D2C, high-ticket travel/tech, and subscription/SaaS.

## 8. Feature-contract and numeric validation

`features_v3_1.csv` contains 20,714 rows. Its model matrix contains exactly the 44 features of `merchant-visible-causal-3.1` in frozen contract order. All 44 model feature columns are finite: no NaN, positive infinity, or negative infinity was found.

## 9. Canonical dataset hashes

- Raw events: `21f1c0db7c370e42a95866fcec4743209e462b452a7f0f66b257e4c35214a570`
- Labels: `79f60ba2eccdef71e673bd70479681f70c04e90e2fb22232b96f2bbb2b9bd056`
- Features v3.1: `b810cf0e7ff9c363267a653be11651d8351ca672b591b63c2c90e59ec795a3c4`
- Canonical manifest: `673eaaf921e85f0ada71028e4bcc94d8ab1d869d429c10fb413cfec8e553012b`
- Freeze manifest: `674268d2d7ac3c313b2d2ca8cd4c16a20f70c65c2e1887d4d8fbaaba0d6f3f78`

## 10. Frozen source hashes

- PBRSS config: `6a7030cda45ab1228f63e1297d0a418a15ca07063c603d3df12e08da59c1b99f`
- Generator: `914d766b3e8f174875e9bc08da7788f88aaf9a24b43096ed4be1ac190ed42725`
- Generation pipeline: `455b3fce8e97a281eb36cd220421b89c67a60bcc27fa08d7213928c51316dff9`
- FeatureEngine v3.1: `bf3d564b1ed696eef937dac7259dba6ad964fe1737115808e0107e22130e6a50`
- Feature replay: `a70cc497cf39e7b4cb64437a6918a703b4f31918baf5bdb69996e4568d004849`
- Evaluation module: `ecc27d8a7e3a53b6f6f3e088fb3bab6fe0044359fc270aa2a7d3aa59826049ce`
- Evaluation pipeline: `c6086713683a1bc473be846c027c3e5a1b1095eec167f146cecadcac052c377e`

## 11. Frozen foundation hashes

- Model v3.1 artifact: `093254b63674f50b62caf5eddeaeba47d79f9327902e2567ffed75418a59b1e4`
- Model v3.1 metadata: `0c6c4f1f30b4e585022189bfdb10e4bf7c6d1efbe646abd1ec5fbdd4dca3592f`
- Feature-contract artifact: `522aa6327617bfed687bd2f0955405b5f63f6595fb0c86da9077b4442af554a8`
- Feature-contract semantic hash: `af66f693eee5043f0e97dfef1c31b1773ae480e38228f47612575d336abe2ce0`
- Policy v2 artifact: `8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c`

Every path referenced by the freeze manifest was independently rehashed and matched.

## 12. Safe preflight

The no-score evaluator preflight returned `status: passed`. It verified freeze bindings, source and artifact hashes, Model v3.1 metadata, sigmoid calibration, the exact feature contract, Policy v2, and absence of prior consumption. No model scoring method was called.

## 13. Validation results

- Targeted PBRSS tests: 19 passed
- Full pytest: 236 passed, 262 deselected
- Test coverage: 89%
- Release verifier: passed
- `git diff --check`: passed

## 14. Evaluation boundary

**NO MODEL v3.1 PBRSS SCORE HAS BEEN COMPUTED**

**PBRSS-v1 REMAINS UNCONSUMED**

**`pbrss_v1_consumption.json` DOES NOT EXIST**
