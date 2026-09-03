# Economic Scenario Analysis Report

## Goal

Translate frozen PBRSS-v1 operating points into reproducible merchant-side economic scenarios to evaluate the trade-off between protected attack losses and legitimate-customer review friction under different attack prevalences.

> **Note:** All monetary values in this report are illustrative merchant scenario parameters, not measured Razorpay financials, production savings, or empirical merchant losses.

## Setup

- **Evaluation Basis:** Frozen device-level PBRSS-v1 performance
- **Frozen Operating Rates:**
  - Attack REVIEW+: **96.40%**
  - Attack BLOCK: **59.12%**
  - Legitimate REVIEW+: **20.72%**
  - Legitimate BLOCK: **0.16%**
  - Legitimate REVIEW-only (`REVIEW+ − BLOCK`): **20.56%**
- **Model & Policy State:** Model v3.1, Policy v2 (both frozen; no rescoring or retuning)
- **Population Baseline:** $N = 100,000$ modeled device checkout opportunities

## What I Tested

- **Cost-Benefit Formula:** Modeled net economic value as protected attack losses minus review friction costs and false-block costs:
  $$V_{\text{net}} = V_{\text{protected}} - C_{\text{review\_total}} - C_{\text{block\_total}}$$
- **Quiet-Day Scenario:** Evaluated low-prevalence baseline traffic (0.10% attack prevalence).
- **Active-Campaign Scenario:** Evaluated elevated attack traffic during an automated card-testing assault (2.00% attack prevalence).
- **High-Value Merchant Scenario:** Evaluated traffic where individual checkout fraud incurs higher financial risk (0.50% prevalence, INR 10,000 attack cost).
- **Break-Even Analysis:** Derived the exact attack prevalence threshold where Sentinel transitions from net-cost to net-positive value.

## Results

### 1. Scenario Summary ($N = 100,000$ Devices)

| Metric | Quiet Day | Active Attack Campaign | High-Value Merchant |
| :--- | ---:| ---:| ---:|
| **Attack Prevalence ($p$)** | **0.10%** | **2.00%** | **0.50%** |
| **Missed Attack Cost ($C_{\text{attack}}$)** | INR 2,000 | INR 2,000 | INR 10,000 |
| **Review Cost ($C_{\text{review}}$)** | INR 40 | INR 40 | INR 100 |
| **Hard Block Cost ($C_{\text{block}}$)** | INR 500 | INR 500 | INR 1,500 |
| Attack Profiles ($A$) | 100.00 | 2,000.00 | 500.00 |
| Legitimate Profiles ($L$) | 99,900.00 | 98,000.00 | 99,500.00 |
| Attacks Surfaced ($A \times 0.964$) | 96.40 | 1,928.00 | 482.00 |
| Attacks Missed ($A \times 0.036$) | 3.60 | 72.00 | 18.00 |
| Legitimate REVIEW-Only ($L \times 0.2056$) | 20,539.44 | 20,148.80 | 20,457.20 |
| Legitimate Hard-Blocks ($L \times 0.0016$) | 159.84 | 156.80 | 159.20 |
| **Protected Attack Value** | **INR 192,800.00** | **INR 3,856,000.00** | **INR 4,820,000.00** |
| No-Sentinel Baseline Cost | INR 200,000.00 | INR 4,000,000.00 | INR 5,000,000.00 |
| Review Friction Cost | INR 821,577.60 | INR 805,952.00 | INR 2,045,720.00 |
| False Hard-Block Cost | INR 79,920.00 | INR 78,400.00 | INR 238,800.00 |
| Total Sentinel Residual Cost | INR 908,697.60 | INR 1,028,352.00 | INR 2,464,520.00 |
| **Net Illustrative Value** | **INR −708,697.60** | **INR +2,971,648.00** | **INR +2,535,480.00** |
| **Position vs. Break-Even** | **Below Break-Even** | **Above Break-Even** | **Above Break-Even** |

### 2. Break-Even Prevalence Analysis

The break-even prevalence $p^*$ represents the exact attack rate where protected attack value equals total legitimate friction cost:

$$p^* = \frac{0.2056 \cdot C_{\text{review}} + 0.0016 \cdot C_{\text{block}}}{0.964 \cdot C_{\text{attack}} + 0.2056 \cdot C_{\text{review}} + 0.0016 \cdot C_{\text{block}}}$$

| Scenario | Modeled Prevalence | Break-Even Prevalence ($p^*$) | Viability Assessment |
| :--- | ---:| ---:| :--- |
| **Quiet Day** | 0.10% | **0.465869%** | Negative net value; friction exceeds attack losses |
| **Active Campaign** | 2.00% | **0.465869%** | Positive net value (+INR 2.97M); high payoff during attacks |
| **High-Value Merchant** | 0.50% | **0.237608%** | Positive net value (+INR 2.54M); high fraud cost justifies review friction |

## What the Results Mean

1. **Prevalence-Dependent Viability:** The economic utility of Sentinel depends directly on the threat environment. During low-prevalence quiet days (0.10%), 20.56% review friction causes negative net value (-INR 708,698).
2. **High Value During Attack Waves:** When card testing surges (2.00% prevalence), detecting 96.40% of attack attempts saves INR 3.86M in fraud losses, easily absorbing review friction costs and delivering +INR 2.97M in net value.
3. **High-Ticket Protection:** For merchants with high fraud consequences, the break-even threshold drops to 0.24%, making fraud prevention economically justified even under elevated review rates.

## Limitations

- **Illustrative Model:** Cost parameters ($C_{\text{attack}}, C_{\text{review}}, C_{\text{block}}$) are hypothetical merchant inputs, not measured gateway data.
- **Fixed Friction Multipliers:** Calculations assume static scalar review costs and do not model manual review queue bottlenecks or customer drop-off dynamics.
- **Not a Production Savings Guarantee:** Positive net values depend on scenario assumptions and do not constitute a financial guarantee for real merchants.

## Reproducibility

- **Scenario Configuration:** `configs/economic_scenarios.yaml`
- **Execution Script:**
  ```bash
  python scripts/run_economic_scenarios.py
  ```
- **Generated Artifact:** `artifacts/economics/phase_4d_economic_scenarios.json`
- **Unit Tests:** `tests/unit/test_phase_4d_economics.py` (18 tests passed)
