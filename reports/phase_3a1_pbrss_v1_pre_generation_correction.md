# Phase 3A.1 — PBRSS-v1 Pre-Generation Design Correction

## Independent-review finding

Independent review of the committed Phase 3A machinery found that the four held-out scenario names existed, but three families had only one or two devices. That made their eventual family-level measurements statistically unhelpful. The original test checked presence rather than evaluation population size.

No authoritative PBRSS dataset had been generated, no Model v3.1 score had been observed, and the suite remained unconsumed. These changes are therefore pre-generation evaluation-design corrections—not reactions to stress results. The issue is recorded openly rather than hidden.

## Frozen allocation correction

The configuration now declares the complete 5,000-device allocation. Attack traffic contains 250 `stealth_low_amount_drip`, 250 `hybrid_credential_stuffing_probe`, and 750 `mixed_card_probe` devices. Legitimate traffic contains 500 `charity_micro_donation_spike`, 250 `b2b_multi_corporate_card`, and 3,000 `ordinary_checkout` devices. This fixes the total at 1,250 attack and 3,750 legitimate devices.

These quotas were selected for neutral evaluation power and frozen independently of Model v3.1 performance.

## Configuration authority

Scenario quotas, attempt ranges, amounts, stealth gaps and duration, charity burst duration and guest distribution, B2B card count, identity-switch behavior, outcome profiles, and request tolerance now come from `configs/post_blind_stress_v1.yaml`. The generator validates configuration totals before emitting data and validates the completed bundle before any canonical file can be written.

## Scenario semantics

- Stealth actors use configured ₹1–₹5 amounts, 7–11 attempts, 18–36-hour authorization gaps, and a maximum ten-day event span.
- Hybrid actors contain only harmless synthetic payment telemetry and switch synthetic customer identity after declines. No credentials, login attack implementation, or external interaction exists.
- Charity traffic contains 500 guest-heavy donors concentrated inside the configured two-hour campaign window. Each donor begins with a synthetic payment/authentication failure and retries; the family is not all successful.
- B2B traffic uses the configured ₹120,000 invoice and four-card rotation, with multiple failures followed by successful procurement completion. It is neither all-success nor all-failure traffic.

## Request-count invariant

The declared 20,000 authorization-request target now has a frozen ±10% tolerance. Generation fails before writing canonical files unless the deterministic request count is between 18,000 and 22,000.

## Outcome-overlap safeguard

The former population-wide 0.35/0.72 approval constants were removed. Configuration now declares overlapping attack and legitimate outcome profiles: low/moderate/camouflage success for attacks and normal/retry-heavy/intermittent success for legitimate users. Hard legitimate families contain meaningful failures, while attacks can contain successful history. Tests verify empirical device-level overlap without using Model v3.1.

## Merchant and shortcut safeguards

All 16 deterministic PBRSS merchant IDs remain disjoint from development-v4.1. Traffic allocation requires both populations at every merchant. Charity and B2B archetypes therefore cannot reveal the label. Shared 80-device network cohorts occur in both attack and legitimate traffic, and scenario/label/generator metadata remains outside the exact 44-feature model matrix.

## Machinery freeze binding

Canonical generation now refuses a dirty working tree and records the then-current committed HEAD as `pbrss_machinery_freeze_commit`. The future dataset freeze will therefore bind both the earlier Model v3.1 freeze commit and the committed PBRSS generator/evaluator machinery, in addition to source and artifact hashes. The future machinery commit is deliberately not hard-coded before it exists.

## Tests

Tests now enforce exact canonical population and scenario quotas, request tolerance, 16 merchants, development merchant disjointness, population coverage, config-driven scenario behavior, stealth timing and amount bounds, charity burst bounds, B2B card rotation and mixed outcomes, overlapping outcome distributions, deterministic bytes, causal feature replay, metadata exclusion, the exact 44-feature contract, clean-tree generation, freeze integrity, and fail-closed one-shot consumption.

## Historical integrity

Model v3.1, its sigmoid calibration, Feature Contract v3.1, Policy v2, the active frozen-v2 runtime, development-v4.1, and all Blind-v2 evidence remain unchanged.

**AUTHORITATIVE PBRSS DATASET NOT GENERATED**

**PBRSS NOT SCORED**

**PBRSS REMAINS UNCONSUMED**
