# Phase 3A — PBRSS-v1 Pre-Generation Audit

## 1. Freeze commit verification

Phase 3A began from clean commit `1c9dab4ed2902b4207e6758f1c929fee1b8a08dc`, the authoritative pre-PBRSS Model v3.1 freeze. The commit was not rewritten or modified.

## 2. Specification implementation mapping

The frozen `pbrss-v1-frozen-spec` is represented by a separate configuration, generator, causal replay pipeline, deterministic freeze builder, and fail-closed one-score evaluator. The historical flat-file naming in the original Phase-1 document is superseded by the single canonical directory `data/generated/post_blind_stress_v1/`; no duplicate authoritative copy is maintained.

## 3. Configuration

`configs/post_blind_stress_v1.yaml` declares generator version `pbrss-v1-generator-1`, seed `773829104`, approximately 5,000 devices and 20,000 requests, a 25% attack-device fraction, 16 merchants over eight archetypes, 55–65% guest traffic, Pareto timing, 1–48 hour attack pauses, 7–14 day long retries, and CGNAT cohorts capped at 80 devices. It contains no observed PBRSS metrics or model-derived generation targets.

## 4. Generator architecture

The generator emits only ordered lifecycle events and device-level evaluation labels. It uses neutral domain primitives, deterministic SHA-256-derived identifiers, an isolated NumPy random stream, stable sorting, and a deterministic manifest without wall-clock fields. Feature construction remains exclusively in `build_feature_table_v3`.

## 5. Held-out scenarios

Implemented scenarios are `stealth_low_amount_drip`, `hybrid_credential_stuffing_probe`, `charity_micro_donation_spike`, and `b2b_multi_corporate_card`. Credential-stuffing behavior is represented only as harmless synthetic defensive telemetry; no credentials, login automation, or external interaction exists.

## 6. Anti-shortcut checks

Random-looking identifiers do not encode class. Every PBRSS merchant receives both attack and legitimate traffic, including B2B and charity archetypes. Guest presence, amount ranges, device structure, IP format, and merchant type overlap across populations. Scenario, population, labels, IDs, counterfactual roles, and generator metadata are excluded from the 44-column model matrix.

## 7. Merchant disjointness

Merchant identifiers are deterministically derived in a `pbs_` namespace from the PBRSS seed and archetype. Tests compare them with the frozen development-v4.1 merchant set and require zero overlap. FeatureEngine v3.1 continues to scope shared-IP history by merchant.

## 8. Determinism guarantees

The same config, seed, and source produce identical CSV bytes and canonical manifest bytes. Different seeds change output. No wall-clock time is consulted during generation, and the dataset manifest has no creation timestamp.

## 9. Feature-contract enforcement

The generation pipeline calls the unchanged `build_feature_table_v3` replay. Freeze and evaluation validate the exact ordered 44-feature `merchant-visible-causal-3.1` contract and its hash. Evaluation rejects reordered/missing features and non-finite values before model loading or scoring.

## 10. One-shot evaluator guardrails

The evaluator rejects a missing freeze, any frozen-file hash drift, an incorrect pre-PBRSS commit binding, incorrect model/metadata/contract/calibration/policy identity, or an existing consumption record. It loads the frozen Model v3.1 artifact without training, applies its sigmoid calibrator and unchanged Policy v2, uses device weights, and atomically reserves consumption after the first successful score but before metric computation or output. A second invocation fails closed.

## 11. Tests added

Phase 3A tests cover deterministic fixture bytes, seed separation, timestamp-free manifests, merchant disjointness and population coverage, held-out families and group coherence, exact causal replay contract, metadata exclusion, current-request causality, generator dependency isolation, freeze/hash/consumption failures, absence of evaluator fitting, frozen-stack bindings, and atomic second-run refusal. Existing FeatureEngine v3 tests continue to cover merchant-scoped IP state.

## 12. Files changed

Created: the PBRSS config, generator, evaluation governance module, two pipelines, two unit-test modules, and this audit report. No frozen Phase 2.6 artifact, development dataset, feature/training config, runtime file, or Blind-v2 evidence was modified.

## 13. Generation confirmation

**AUTHORITATIVE PBRSS DATASET NOT GENERATED**

## 14. Scoring confirmation

**PBRSS NOT SCORED**

## 15. Consumption confirmation

**`pbrss_v1_consumption.json` DOES NOT EXIST**
