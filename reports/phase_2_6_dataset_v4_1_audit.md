# Dataset v4.1 Audit Report

## Goal

Audit Dataset v4.1 (`development-v4.1`) to verify synthetic data generation integrity, ensure balanced scenario coverage, and prove leak-free cross-validation partitioning.

## Setup

- **Dataset:** `development-v4.1`
- **Generator Version:** `dataset-v4.1-generator-1`
- **Feature Contract:** `merchant-visible-causal-3.1` (44 features)
- **Status:** PASSED

## What I Tested

- **Volume and Scenario Quotas:** Checked total events, authorization requests, and per-family device quotas across 20 merchants and 6 business archetypes.
- **Leakage and Fold-Partitioning:** Verified that multi-device actors, campaigns, households, and counterfactual twin pairs are assigned to unified correlation units (`leakage_group_id`) to prevent fold-straddling.
- **Generator Corrections:** Audited eight generator corrections covering device spread, identity rotation, and historical checkout seeds.
- **Counterfactual Twin Construction:** Verified behavioral parity and causal feature separation across all 20 counterfactual twin pairs.
- **Shortcut Feature Risks:** Checked single-feature predictive power against PR-AUC thresholds to confirm no identifier or metadata leakage.

## Results

### Canonical Artifacts

| Artifact | SHA-256 |
|---|---|
| `raw_events.csv` | `9024c24fafa9dbd214781e897acbf134d3ab5dbf8ae3d1ffebb45fcce10ae1df` |
| `labels.csv` | `e0613eaba2ee792fbe4e70f0e8a4f5c1ac369cb8fa42902c3c266a029141b81e` |
| `features_v3_1.csv` | `882c4c70a292f0363939107bb3fa8d3f88c50530c0734fd7f6070b76a7859d2e` |
| `manifest.json` | `9598be1c8f942a3a4bac4d713298506186620a3267a9d1d8b2541e42ce34071e` |

### Population and Critical Family Coverage

- **Total lifecycle events:** 179,283
- **Authorization requests:** 69,274
- **Total devices:** 12,000
- **Attack prevalence:** 18.0% by device (17.24% request-weighted)
- **Merchants:** 20 across 6 archetypes (subscription, micro-payment, guest-heavy, standard e-commerce, flash sale, high ticket)

| Critical Family | Population | Devices | Quota Status |
|---|---|---:|---|
| `cross_device_weak_guest` | Attack | 557 | Exceeds 250 min |
| `cross_device_partial` | Attack | 504 | Exceeds 250 min |
| `distributed_bot_campaign` | Attack | 362 | Exceeds 250 min |
| `subscription_dunning_hard` | Legitimate | 1,218 | Exceeds 250 min |
| `persistent_card_problem_hard` | Legitimate | 1,039 | Exceeds 250 min |
| `network_retry_storm_hard` | Legitimate | 1,043 | Exceeds 250 min |
| `shared_household_device` | Legitimate | 917 | Exceeds 250 min |
| `cgnat_mobile_ip_storm` | Legitimate | 912 | Exceeds 250 min |

### Partitioning and Correlation-Unit Integrity

`leakage_group_id` is evaluation metadata only and never enters the 44-feature matrix.
- **TRAIN leakage groups:** 6,751 (381 multi-device groups; largest: 50 devices)
- **TRAIN / validation leakage group overlap:** 0
- **TRAIN / validation actor overlap:** 0
- **TRAIN / validation customer overlap:** 0
- **Fold-straddling groups across cross-validation:** 0
- **Campaign and household fold overlap:** 0

### Generator Corrections Verified

1. Spread actors transact on every allocated device.
2. Weak-guest actors use 4–8 devices, CGNAT clusters use 20 devices on one IP, and distributed campaigns use 50 devices/IPs.
3. Scenario selection weights normalize by expected devices per actor to prevent large campaigns from skewing device coverage.
4. Household events rotate through 2–3 declared customer identities.
5. `network_instability` influences outcome generation.
6. Repeat-amount scenarios maintain consistent amounts.
7. Established actors receive realistic historical successful checkouts.
8. Generation no longer embeds wall-clock timestamps, ensuring byte-identical reproducibility.

### Counterfactual Construction and Shortcut Audit

- All 20 declared counterfactual twin pairs were realized. Each pair shares merchant, start time, attempt count, amount, and surface cadence, differing only in causal risk properties (card reuse, identity continuity, clean history).
- No feature leaks label, split, scenario, or actor metadata.
- Highest single-feature PR-AUC was causal `card_diversity_ratio_7d` (0.7619). Raw `current_amount` scored PR-AUC 0.5062 (non-shortcut baseline).

## What the Results Mean

Dataset v4.1 provides a clean synthetic training and validation environment. By enforcing strict group-level partitioning and eliminating shortcut pseudo-features, model evaluation measures actual behavioral learning rather than synthetic artifacts or cross-device leakage.

## Limitations

- **Synthetic Data:** Dataset v4.1 is a synthetic simulation environment designed to stress specific card-testing and legitimate retry failure modes. It is not real Razorpay production data.
- **Simulated Pacing:** Pacing, retry distributions, and card-testing patterns reflect modeled archetypes rather than empirical gateway traffic.

## Reproducibility

- **Audit Script:**
  ```bash
  python scripts/audit_dataset_v4.py
  ```
- **Dataset Configuration:** `configs/dataset_v4_1.yaml`
