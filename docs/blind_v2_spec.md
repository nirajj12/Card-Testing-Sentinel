# Blind v2 specification

Blind v2 is an independent, temporally later, composition-shifted synthetic
benchmark for the frozen Feature Contract v2 / Model v2 / Policy v2 stack. Phase 12
creates, validates, and freezes only the dataset. No model score, policy decision, or
performance metric may be produced until the separately approved one-time Phase 13
evaluation.

## Independence and chronology

The benchmark uses seed `817263541`, namespace `bv2`, new merchant instances, new
actor/customer/device/session/IP/request/event identifiers, and a window beginning
2027-06-01—strictly after Dataset v3's final event. It is generated from latent
behavioral mechanisms into raw merchant-visible lifecycle events. Dataset v3 or
Blind v1.1 rows are never sampled or perturbed.

The generator may import neutral event, merchant, and payment-mechanics primitives.
It may not import modeling, policy, training, evaluation, policy-search, or frozen
artifacts. Scenario population is evaluation metadata only: authorization behavior
is driven by scenario parameters and never branches on label/population.

## Shift design

Blind v2 targets roughly 4,000 devices and a deliberately enriched 20% attack-device
share. This is a reporting sample choice, not prevalence. It changes merchant mix,
adds grocery-delivery and SaaS-tool merchants, shifts amount/cadence ranges, lowers
and varies identity availability, increases legitimate shared-network traffic, and
uses a later, longer horizon.

Attack families cover fast bursts, burst-pause-burst, variable cadence, success
camouflage, normal merchant amounts, session churn, strong/partial/weak cross-device
linkage, sparse multiday behavior, patient and ultra-patient behavior, long warm-up,
and mixed campaign behavior. Patient actors make 3–8 attempts with common 1–4 day
gaps; ultra-patient actors make 3–7 attempts with 2–6 day gaps and occasional 7–18
day gaps. They use normal amounts and intentionally carry little short-window
velocity. Sparse actors include same-device, partially linked multi-device, and
weak/guest histories.

Cross-device actors use 2–8 devices. Strong linkage usually shares one customer;
partial linkage mixes guest requests, one shared customer, and device-local
customers; weak linkage is mostly guest or device-local. Sentinel is not expected to
connect completely unrelated anonymous devices.

Warm-up actors create plausible earlier successful-payment opportunities before
switching latent behavior. Main activity begins 8–52 days later, so some prior
successes naturally age outside 30 days. Customer history is helpful but not a
guarantee of legitimacy.

Legitimate families cover subscription dunning, genuine persistent card problems,
network retry storms, mobile churn, household/campus/office shared infrastructure,
multi-device customers, dormant returners, campaign rushes, high-value retries,
micro-payments, guests, and established returners. Dunning mixes newer and older
subscriptions and overlaps attacks on failures, active days, retries, sessions, and
IP behavior.

## Causality and labels

Authorization requests contain only facts available before the current outcome.
PAN, CVV, expiry, current/future outcome, intent, scenario, and label never appear.
Verified outcome/card metadata arrives only on later outcome events. Labels and
scenario/linkage metadata live in `labels.csv` and are joined only after FeatureEngine
v2 replay for dataset validation.

## Pre-evaluation gates

Before freeze, Phase 12 requires lifecycle integrity, complete scenario and merchant
realization, active attack devices, deterministic byte output, no identity overlap
with Dataset v3 or Blind v1.1, strict chronology, all four guest/logged-in ×
attack/legitimate cells, legitimate multi-device customers, all linkage classes,
patient/sparse/warm-up/dunning behavior, no future leakage, `one_feature_max_f1 <=
0.85`, shuffled-label ROC-AUC <= 0.60, and meaningful population overlap.

FeatureEngine v2 may produce `features_v2.csv` solely for leakage, replay, and shift
diagnostics. Model v2 and Policy v2 must never be loaded or invoked. PSI, KS, overlap,
identity/merchant/scenario/timing/amount/multiplicity summaries are dataset-only
diagnostics, not performance results.

## Freeze protocol

First freeze the development dependencies and Blind v1.1 preservation boundary.
Then freeze this specification, configuration, and versioned generation sources.
Generate twice from clean in-memory state and require byte-identical raw events,
labels, features, and manifest. After validation passes, freeze the dataset,
validation report, shift report, and reproducibility record. The final manifest must
state `evaluated: false` and `consumed: false`.
