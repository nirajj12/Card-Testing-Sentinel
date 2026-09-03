# Evaluation, Runtime, and Economic Figures Report

## Goal

Document the presentation figures generated directly from committed frozen evaluation, diagnostic, latency, and economic artifacts without model rescoring.

## Setup

- **Source Artifacts:** All figures are rendered strictly from committed CSV and JSON evidence.
- **Model State:** Model v3.1 and Policy v2 are frozen; zero rescoring, retraining, or recalibration was performed.
- **Output Directory:** `artifacts/figures/` (7 PNG charts + 1 provenance manifest)

## What I Tested

- **Attack Coverage Across Scenarios:** Visualized family-level recall and hard-blocking rates on shifted stress attacks.
- **Detection Delay Progression:** Plotted cumulative detection curves across sequential transaction attempts.
- **Legitimate Friction Concentration:** Visualized where false-review friction manifests across legitimate cohorts.
- **Probability Calibration:** Plotted observed attack rates versus predicted risk across 10 reliability bins.
- **Covariate Shift (PSI):** Visualized the top 10 shifted features between development data and ordinary checkout.
- **Precheck Latency Distribution:** Plotted response latency percentiles from 500 local HTTP requests.
- **Economic Value Scenarios:** Visualized protected value versus friction costs across three merchant operating profiles.

## Results

### 1. Catalog of Generated Figures

| Figure | Image File | Authoritative Data Source | Key Observation |
| :--- | :--- | :--- | :--- |
| **1. Attack Scenario Coverage** | `pbrss_scenario_performance.png` | `artifacts/evaluation/pbrss_v1_family_metrics.csv` | 100.0% REVIEW+ on stealth attacks; 60.8% BLOCK on hybrid probes; 44.93% BLOCK on mixed-card probes. |
| **2. Detection Delay** | `pbrss_detection_delay.png` | `artifacts/evaluation/pbrss_v1_detection_delay.json` | Detection rises sharply from 23.2% at attempt 1 to 92.16% by attempt 3 and 96.4% by attempt 5. |
| **3. Legitimate Friction** | `pbrss_legitimate_friction.png` | `artifacts/evaluation/pbrss_v1_family_metrics.csv` | Friction concentrates in ordinary checkout (25.3% REVIEW+, 0.13% BLOCK); 0.0% in charity traffic. |
| **4. Calibration Curve** | `pbrss_calibration.png` | `pbrss_v1_calibration.csv` & `pbrss_v1_metrics.json` | Brier = 0.1560, ECE = 0.1407 across 10 bins; reveals probability drift under shifted stress. |
| **5. Covariate Shift (Top PSI)** | `phase_4a_feature_shift.png` | `phase_4a_ordinary_checkout_feature_shift.csv` | Top shifts: `device_age_seconds` (6.85), `seconds_since_last_payment` (6.82), `customer_age_seconds` (6.38). |
| **6. Runtime Precheck Latency** | `phase_4c_latency.png` | `artifacts/runtime/phase_4c_precheck_latency.json` | p50 = 33.83 ms, p90 = 87.78 ms, p95 = 110.73 ms, p99 = 183.19 ms over 500 sequential requests. |
| **7. Economic Scenarios** | `phase_4d_economic_scenarios.png` | `phase_4d_economic_scenarios.json` | Quiet day: -INR 708.7K; Active attack: +INR 2.97M; High-value merchant: +INR 2.54M. |

### 2. Embedded Visual Evidence

#### Attack Scenario Performance
![Attack coverage across shifted stress scenarios](../artifacts/figures/pbrss_scenario_performance.png)

#### Detection Delay Progression
![Behavioral history drives detection](../artifacts/figures/pbrss_detection_delay.png)

#### Legitimate User Friction
![Where legitimate-user friction concentrates](../artifacts/figures/pbrss_legitimate_friction.png)

#### Reliability & Calibration Under Stress
![Calibration under shifted stress traffic](../artifacts/figures/pbrss_calibration.png)

#### Feature Covariate Shift in Ordinary Checkout
![Top covariate shifts in ordinary checkout traffic](../artifacts/figures/phase_4a_feature_shift.png)

#### Precheck Decision Latency
![Local precheck latency](../artifacts/figures/phase_4c_latency.png)

#### Economic Impact Trade-Offs
![Illustrative economics depend on merchant context](../artifacts/figures/phase_4d_economic_scenarios.png)

## What the Results Mean

1. **Clear Visual Narrative:** The charts clearly visualize both the system's core strength (rapid multi-attempt detection reaching 96.4% recall) and its primary operational limitation (review friction concentrated in ordinary checkout).
2. **Strict Provenance:** Every figure is generated deterministically from an existing structured artifact and logged in `figure_manifest.json` with its corresponding SHA-256 hash.

## Limitations

- **Synthetic Evidence Base:** Charts describe synthetic benchmarks and local measurements; they do not represent live production gateway traffic.
- **Scalar Economic Assumptions:** Economic charts illustrate merchant cost sensitivity under specific assumed parameters rather than verified financial savings.
- **No Production Readiness Claim:** Charts truthfully display the `MIXED` evaluation result and do not claim production readiness.

## Reproducibility

- **Generation Script:**
  ```bash
  python scripts/generate_final_figures.py
  ```
- **Provenance Manifest:** `artifacts/figures/figure_manifest.json`
- **Unit Tests:** `tests/unit/test_phase_5a_figures.py` (8 tests passed)
