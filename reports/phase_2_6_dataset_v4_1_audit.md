# Phase 2.6 Dataset v4.1 Audit

**Status:** PASSED  
**Dataset:** `development-v4.1`  
**Generator:** `dataset-v4.1-generator-1`  

## Canonical artifacts

| Artifact | SHA-256 |
|---|---|
| `raw_events.csv` | `9024c24fafa9dbd214781e897acbf134d3ab5dbf8ae3d1ffebb45fcce10ae1df` |
| `labels.csv` | `e0613eaba2ee792fbe4e70f0e8a4f5c1ac369cb8fa42902c3c266a029141b81e` |
| `features_v3_1.csv` | `882c4c70a292f0363939107bb3fa8d3f88c50530c0734fd7f6070b76a7859d2e` |
| `manifest.json` | `9598be1c8f942a3a4bac4d713298506186620a3267a9d1d8b2541e42ce34071e` |

The canonical manifest has no execution timestamp. A second generation from
the same config, seeds, and sources is required to reproduce these hashes.

## Population and coverage

- 179,283 lifecycle events
- 69,274 authorization requests
- 12,000 devices
- 18.0% attack prevalence by device (the 17.24% audit-table prevalence is
  request-row weighted and is not the configured device prevalence)
- 20 merchants across all six declared archetypes
- all eight critical families exceed 250 devices

| Critical family | Devices |
|---|---:|
| cross_device_weak_guest | 557 |
| cross_device_partial | 504 |
| distributed_bot_campaign | 362 |
| subscription_dunning_hard | 1,218 |
| persistent_card_problem_hard | 1,039 |
| network_retry_storm_hard | 1,043 |
| shared_household_device | 917 |
| cgnat_mobile_ip_storm | 912 |

## Correlation-unit integrity

`leakage_group_id` is label/evaluation metadata and is absent from the 44
model features. It maps each actor, campaign, household, or counterfactual
pair to its largest correlated synthetic unit.

- TRAIN groups: 6,751
- TRAIN multi-device groups: 381
- largest group: 50 devices
- TRAIN/validation leakage-group overlap: 0
- TRAIN/validation actor overlap: 0
- TRAIN/validation customer overlap: 0
- CV fold-straddling groups: 0
- campaign fold overlap: 0
- household fold overlap: 0

## Generator corrections

- Spread actors now transact on every allocated device.
- Weak-guest actors use 4–8 devices, CGNAT clusters use 20 devices on one
  merchant-scoped IP, and distributed campaigns use 50 devices/IPs.
- Scenario selection weights are normalized by expected devices per actor,
  preventing large groups from dominating device coverage.
- Household events rotate through the declared 2–3 customer identities.
- `network_instability` now affects outcome generation.
- Repeat-amount scenarios retain a common amount.
- Established actors receive actual historical successful checkouts.
- Canonical generation no longer embeds wall-clock time.

## Counterfactual construction

All 20 Phase-1 pair IDs are realized. Each pair shares one merchant, one
start time, current-attempt count, amount, and an explicit cadence/device
surface. The twins differ through declared causal properties such as card
reuse/diversity, identity continuity, and clean history. Both twins share one
evaluation leakage group; pair ID and role never enter the feature matrix.

## Shortcut audit

No feature name or value consumes label, population, scenario, actor ID,
leakage group, pair ID, pair role, merchant kind, or split. Generated IDs use
the same format across labels within a split and are linking metadata only.
Missing customer identity is neutral in customer aggregates and separately
represented by `customer_id_present`.

No individual feature exceeded the hard-fail PR-AUC threshold. The strongest
single feature was causal `card_diversity_ratio_7d` (PR-AUC 0.7619). Raw
`current_amount` remains a monitored synthetic-domain shortcut risk (PR-AUC
0.5062), but it is a genuine current-request fact, stable across splits, and
is not derived from merchant archetype or label metadata.
