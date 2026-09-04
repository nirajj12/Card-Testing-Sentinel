# Project Overview

## The problem

Card testing is automated checkout abuse. An attacker repeatedly tries payment
credentials, often using small amounts, to discover which cards can be used.
A genuine customer can also have a decline or retry, so one failed payment is
not enough to prove an attack.

## What makes Sentinel different

Many fraud systems classify a transaction after it exists. Sentinel operates
earlier: it decides whether suspicious checkout behavior should reach Razorpay
at all.

```text
Checkout intent
→ behavioral precheck
→ risk score
→ policy action
→ Razorpay order only after ALLOW
```

Sentinel complements gateway and issuer fraud controls. It does not replace
Razorpay fraud systems, issuer checks, 3DS, OTP, or human fraud analysts.

## The three proof layers

| Layer | Purpose |
|---|---|
| **Protected Checkout** | Uses real Razorpay Standard Checkout in Test Mode to prove that Sentinel gates order creation. |
| **Replay Lab** | Sends controlled synthetic behavior through the same scoring runtime to show one sequence attempt by attempt. Decisions are computed at runtime, not predefined. |
| **Evaluation** | Measures aggregate detection, friction, ranking, and calibration on frozen synthetic datasets. |

These layers answer different questions. Replay Lab is not Razorpay traffic,
and a convincing replay is not a population-level evaluation result.

## Current status

The active prototype uses Model v3.1, 44 causal features, and Policy v2. Its
shifted-stress verdict is `MIXED`, and `production_ready=false`. The project
shows a working architecture and measurable behavior, but it does not claim
production fraud performance.
