# Dataset v4 Scenario Matrix, Merchant Archetypes & Paired Counterfactual Benchmark

This document defines the complete operational scenario taxonomy, merchant archetypes, and paired counterfactual benchmark for Dataset v4 and the post-Blind development cycle.

---

## Part 1: Merchant Archetypes & Contextual Baselines

In payment security, an absolute threshold is inherently flawed: 8 requests in 3 minutes is suspicious for a bespoke furniture store, but entirely routine during an active ticket drop or flash sale. Dataset v4 formalizes **6 merchant archetypes** to support future merchant-relative features:

| Archetype | Traffic Profile | Typical Amount ($\mu$, $\sigma$) | Guest / Account Ratio | Normal Velocity (attempts/min) | Normal Card Diversity | Base Decline Rate | Common Legitimate Friction Pattern |
|---|---|---|---|---|---|---|---|
| **1. Standard E-commerce** | Steady, business hours diurnal cycle | ₹1,500 ($\pm$ 40%) | 25% Guest / 75% Login | 0.2 – 0.5 | 1.1 cards / 30d | 4% – 7% | Multi-card retry when 1st card has insufficient balance. |
| **2. Guest-Heavy D2C** | Campaign driven, social ad traffic | ₹850 ($\pm$ 35%) | **75% Guest** / 25% Login | 0.3 – 0.8 | 1.0 cards / 30d | 5% – 9% | Fast guest checkout from mobile Instagram webview with session drops. |
| **3. Subscription / SaaS** | Batch renewal spikes on 1st/30th | ₹599 ($\pm$ 15%) | **2% Guest** / 98% Login | 0.05 – 0.2 | 1.0 cards / 30d | **12% – 20%** | Scheduled dunning retries on expired cards across multiple days. |
| **4. Micro-Payment & Digital** | Continuous, low latency, impulsive | ₹79 ($\pm$ 60%) | 45% Guest / 55% Login | 0.8 – 2.0 | 1.2 cards / 30d | 4% – 8% | Rapid sequential purchases for in-game or media micro-items. |
| **5. Flash-Sale Platform** | Extreme burst spikes (100x baseline) | ₹1,899 ($\pm$ 25%) | 55% Guest / 45% Login | **3.0 – 8.0** | 1.4 cards / 30d | **15% – 25%** | Network retry storms, concurrent browser tabs, 3DS gateway timeouts. |
| **6. High-Ticket Travel/Tech**| Low volume, weekend peaks | ₹28,000 ($\pm$ 75%)| 15% Guest / 85% Login | 0.05 – 0.15 | 1.8 cards / 30d | 8% – 14% | Bank limit rejections followed by testing alternative personal cards. |

---

## Part 2: Legitimate Scenario Design (Hard Negatives Focus)

### 2.0 Device Coverage Architecture & Blind-v2 Covariate Shifts
Coverage in Dataset v4 is designed around **devices/entities per scenario**, rather than aggregate requests alone. High-priority attack and hard-negative families target **250–300 devices each** where feasible, ensuring that device-level metrics (e.g. Review+, Block, First Detection Attempt) do not suffer from small-sample statistical volatility.

Furthermore, the scenarios deliberately incorporate the largest Blind-v2 covariate shifts by crossing orthogonal axes:
- **`device_age_seconds` & `customer_age_seconds`**: Old customer on new device; new customer on aged device; established customer with steady device.
- **`active_day_count_7d` & `gap_variability`**: Regular automated retry cadence ($\text{CV} < 0.2$); irregular human browsing ($\text{CV} \approx 1.0$); bimodal burst-pause ($\text{CV} > 2.5$).
- **`session_age_seconds`**: Short single-page checkouts vs multi-hour browsing sessions vs rapid session resets from flaky browser webviews.
- **`current_amount`**: Shifted amount distributions across archetypes, micro-purchases in gaming vs large tickets in electronics.
- **Behavioral Drift**: Long-established customer temporarily behaving unusually (e.g. sudden retry burst after months of dormancy) vs new guest with clean single-attempt purchase.

### 2.1 Basic Legitimate Scenarios

1. **Normal Returning Customer**
   - *Archetype*: Standard E-commerce.
   - *Customer History*: 180 days tenure, 14 prior successful checkouts, saved card profile.
   - *Behavior*: 1 attempt, single saved card, amount ₹1,499. Instant authorization.
   - *Differentiating Signal*: Long customer age, zero prior declines, established device fingerprint.

2. **Normal Guest Checkout**
   - *Archetype*: Guest-Heavy D2C.
   - *Customer History*: None (`customer_id` is null).
   - *Behavior*: 1 attempt, ₹799, new device, single card.
   - *Differentiating Signal*: Single attempt, normal form completion dwell time, no subsequent retry.

3. **New Customer Onboarding**
   - *Archetype*: Subscription / SaaS.
   - *Customer History*: Account created 3 minutes prior (`customer_age_seconds` $\approx 180$).
   - *Behavior*: 1 attempt for trial verification (₹2), single card.
   - *Differentiating Signal*: Zero failure history, single session, clean IP.

4. **Multi-Card Legitimate Customer**
   - *Archetype*: High-Ticket Travel/Tech.
   - *Customer History*: 2 years tenure, ₹150,000 lifetime spend.
   - *Behavior*: Attempting ₹45,000 flight booking. Card 1 declined (daily bank limit exceeded). Customer immediately tries Card 2 (corporate card) and succeeds.
   - *Differentiating Signal*: Two distinct cards, but established account, realistic high amount, successful completion on second card.

---

### 2.2 Hard Legitimate Negatives (Post-Blind Failure Remediation)

The following scenarios directly address the failures that caused 14.91% legitimate Review+ and 5.09% legitimate Block on Blind v2:

| Scenario Name | Archetype | Cadence & Velocity | Card Diversity | Customer ID & History | Why It Resembles Card Testing | Why It Is NOT Card Testing (Causal Proof) |
|---|---|---|---|---|---|---|
| **`subscription_dunning_hard`** | Subscription | 1 retry every 24h for 5 days | **Exact same card (1 card)** | `customer_id` present; 12 prior monthly successes | 5 consecutive declines in 7 days; `failure_ratio_24h = 1.0` | `distinct_card_last4_7d = 1`; `card_change_after_decline = 0`; 12 historical successful renewals. |
| **`network_retry_storm_hard`** | Flash-Sale | 5 attempts in 45 seconds | **Exact same card (1 card)** | Guest or Login; clean IP | 5 requests in 60s; rapid attempt burst | Identical card hash; identical amount (₹1,899); inter-attempt gap $< 8$s (client auto-retry); no card rotation. |
| **`cvv_and_expiry_mistakes`** | Standard Retail | 3 attempts in 2 minutes | **Exact same card (1 card)** | Account present; 4 months old | 2 declines followed by 1 success in 2 minutes | Same card number used across all 3 attempts; amount constant; third attempt succeeds. |
| **`genuine_wallet_cycling`** | High-Ticket | 4 attempts across 3 cards in 8 minutes | 3 cards (same billing address) | Verified customer with 5 prior orders | 3 cards tested in rapid succession; 2 initial declines | Customer tenure 300 days; all cards share same cardholder name; transaction amount is high (₹32,000). |
| **`shared_household_device`** | Standard Retail | 3 orders in 15 minutes | 3 distinct cards, 2 different customer accounts | 2 distinct `customer_id`s on 1 `device_id` | Multiple cards and identities on single physical device | Device age $> 90$ days; each customer has clean historical record; household order amounts normal. |
| **`cgnat_mobile_ip_storm`** | Guest-Heavy | 25 requests in 10 minutes from 1 IP | 25 distinct cards across 20 devices | 20 independent guest devices | High IP velocity (`requests_per_ip_5m = 25`) | `devices_per_ip_24h` high, but *each device has only 1 attempt*; cellular subnet (Jio/Airtel CGNAT). |
| **`session_recreation_flaky_net`**| Guest-Heavy | 4 attempts in 3 minutes across 4 sessions | **Exact same card (1 card)** | Guest checkout | 4 new sessions in 3 minutes (`sessions_24h = 4`) | Single card used; session churn driven by mobile browser reloading page on disconnect, not credential rotation. |
| **`dormant_account_spike`** | Standard Retail | 3 attempts after 180 days silence | 2 cards (1 expired, 1 new replacement) | Established account, last active 6 months ago | Sudden velocity spike after prolonged dormancy | Customer age $> 200$ days; 1st card fails (expired); customer updates card to new card and succeeds. |

---

## 3. Attack Scenario Design (Targeting Weak Areas)

Attack scenarios in Dataset v4 prioritize the distributed, weak-linkage, and patient strategies that evaded Model v2.

### 3.1 Weak-Linkage & Distributed Campaigns (Priority Remediation)

1. **`cross_device_weak_guest` (Top Priority)**
   - *Architecture*: Attacker uses headless browser farm or botnet. Generates 8–15 attempts across 4–8 distinct device fingerprints.
   - *Identity*: 100% Guest checkout (`customer_id` is null).
   - *IP & Session*: Sessions are rotated every attempt. IPs rotate across commercial proxy subnets (e.g., residential proxies).
   - *Card Diversity*: 1 distinct card per attempt (8 attempts = 8 cards).
   - *Amount*: Low ticket (₹49 – ₹99).
   - *What Makes It Difficult*: No single device exceeds 2 attempts; no `customer_id` exists to link them.
   - *Detectable Precheck Signals*: IP-subnet burst density; identical user-agent/fingerprint entropy anomalies; burst timing coordination across distributed threads; micro-ticket amount consistency across guest sessions.

2. **`cross_device_partial`**
   - *Architecture*: Attacker rotates devices (3–6 devices) but occasionally reuses an IP subnet or session token.
   - *Identity*: 30–50% spoofed customer accounts, 50% guest.
   - *Card Diversity*: High (5–10 cards).
   - *Cadence*: Interleaved across 2–6 hours.
   - *Detectable Precheck Signals*: Multiple new devices appearing on the same IP within hours (`devices_per_ip_24h >= 3`); immediate card rotation following declines.

3. **`distributed_bot_campaign` (New in v4)**
   - *Architecture*: Coordinated testing of 50 stolen cards distributed across 50 distinct IPs and 50 devices against a single merchant.
   - *Identity*: Guest mode.
   - *Cadence*: 1 attempt per minute smoothly distributed.
   - *Detectable Precheck Signals*: Merchant-level velocity anomaly (merchant overall request rate exceeds 3x baseline); amount anomaly (identical non-round amounts like ₹67.40); 100% new device ratio.

---

### 3.2 Sophisticated Single-Device & Patient Attacks

4. **`patient_tester_v4` & `ultra_patient_v4`**
   - *Architecture*: Single actor testing 1 card every 24 to 72 hours.
   - *Card Diversity*: 1 new card per test event.
   - *Dwell Time*: 3 to 14 days total span.
   - *Camouflage*: Normal checkout amounts matching the merchant typical range.
   - *Detectable Precheck Signals*: High `failures_7d` and `decline_streak` combined with `distinct_card_last4_7d >= 3` on the same device; zero completed checkouts despite multiple sessions.

5. **`burst_pause_burst_v4`**
   - *Architecture*: Attacker fires 3 attempts in 30 seconds, pauses for 4 hours to clear in-memory rate limiters, then fires another burst of 4 attempts.
   - *Detectable Precheck Signals*: `requests_5m` resets during the pause, but `requests_24h` and `failures_7d` accumulate; gap variability is extremely bimodal.

6. **`success_camouflage_v4`**
   - *Architecture*: Attacker validates 1 valid card (which succeeds), then immediately tests 5 stolen cards under the cover of the successful session.
   - *Detectable Precheck Signals*: While `seconds_since_last_success` is low, `card_change_after_decline` is high and `distinct_card_last4_7d` increases rapidly post-authorization.

---

## 4. Deliverable D: Paired Counterfactual Benchmark Design

To provide an incontrovertible, domain-specific evaluation of Model v3's causal understanding, Dataset v4 establishes the **Paired Counterfactual Benchmark**.

### 4.1 Methodology & Construction Rules
For every attack scenario, we generate an exact **Legitimate Twin** that matches the attack in superficial observable features (attempt count, velocity window, ticket amount, device freshness), differing **only** in causal history, card diversity, and continuity:

```text
                  Attack Twin                              Legitimate Twin
┌──────────────────────────────────────────────┐ ┌──────────────────────────────────────────────┐
│ Attempts: 6 in 3 minutes                    │ │ Attempts: 6 in 3 minutes                    │
│ Amount: ₹199 each                           │ │ Amount: ₹199 each                           │
│ Merchant: Standard E-commerce               │ │ Merchant: Standard E-commerce               │
│ Device: Single device                       │ │ Device: Single device                       │
│ Cards Tested: 5 distinct cards               │ │ Cards Tested: 1 single card (mistyped CVV)   │
│ Customer: New guest (0 prior history)       │ │ Customer: Established (12 prior checkouts)  │
│ Card Change After Decline: YES (4 times)     │ │ Card Change After Decline: NO (0 times)      │
└──────────────────────────────────────────────┘ └──────────────────────────────────────────────┘
```

### 4.2 Counterfactual Pairs Specification (20 Core Pairs)

| Pair ID | Scenario Archetype | Attack Variant | Legitimate Twin | Identical Surface Features | Differentiating Causal Ground Truth |
|---|---|---|---|---|---|
| **CP-01** | Rapid Burst | `fast_burst` (6 cards, 60s) | `network_retry_storm` (1 card, 60s) | 6 attempts, 60s window, ₹499 | Attack cycles 6 cards; Twin retries 1 card due to network drops. |
| **CP-02** | Dunning / Periodic | `patient_tester` (4 cards, 4 days) | `subscription_dunning` (1 card, 4 days)| 4 attempts, 1 per day, ₹599 | Attack uses 4 cards; Twin uses 1 card with 12 mo prior tenure. |
| **CP-03** | Micro-Payment | `micro_attack` (8 cards, ₹20) | `in_game_micro_shopper` (1 card, ₹20) | 8 attempts in 5m, ₹20 each | Attack rotates cards; Twin is single saved card buying game credits. |
| **CP-04** | Distributed Device | `cross_device_weak` (4 devs, 4 cards)| `household_shopping` (4 devs, 2 cards)| 4 devices, same IP subnet, 2h | Attack has 0 clean history; Twin has established family accounts. |
| **CP-05** | Guest Checkout | `guest_burst` (5 cards, 3m) | `guest_cvv_mistake` (1 card, 3m) | Guest mode, new device, 5 attempts | Attack cycles 5 cards; Twin retries same card correcting CVV. |
| **CP-06** | Multi-Day Sparse | `sparse_multiday` (5 cards, 10 days)| `intermittent_shopper` (2 cards, 10d) | 5 attempts over 10 days, ₹1,200 | Attack has 5 distinct declines; Twin has prior successes and 1 retry. |
| **CP-07** | Session Churn | `session_churn` (6 sessions, 6 cards)| `browser_cookie_block` (6 sess, 1 card)| 6 sessions created in 10m | Attack tests 6 cards; Twin is user with incognito/ad-blocker. |
| **CP-08** | Success Interleaving| `success_camouflage` (1 pass, 4 test)| `repeat_bulk_buyer` (1 pass, 4 items) | 5 checkouts in 15m, 1st succeeds | Attack changes card on attempt 2–5; Twin uses same approved card. |
| **CP-09** | Flash-Sale Drop | `drop_sniping_bot` (8 cards, 30s) | `flash_sale_manual` (1 card, 30s) | Extreme velocity during flash sale | Attack cycles stolen cards; Twin repeatedly clicks 'Pay' on 1 card. |
| **CP-10** | High-Ticket Retry | `luxury_card_probe` (3 cards, ₹45k) | `limit_split_buyer` (2 cards, ₹45k) | 3 high-value attempts in 10m | Attack uses stolen BINs; Twin is genuine user calling bank. |
| **CP-11** | Variable Cadence | `variable_cadence` (7 cards, jitter) | `flaky_3g_commuter` (1 card, jitter) | Irregular 10s–300s gaps, 7 attempts | Attack tests cards; Twin travels through cellular dead zones. |
| **CP-12** | CGNAT Subnet | `proxy_farm` (12 devs, 12 cards) | `university_campus` (12 devs, 12 cards)| 12 devices from 1 `/24` IP prefix | Attack coordinated in 3m; Twin is distinct students buying food. |
| **CP-13** | Identity Churn | `account_churn` (4 accounts, 1 dev)| `family_tablet` (3 accounts, 1 dev) | Multiple accounts on 1 tablet | Attack uses fake accounts; Twin has shared family history. |
| **CP-14** | Expired Card Update | `expired_bin_test` (5 cards, ₹100) | `card_expiry_update` (2 cards, ₹100)| 1 decline then immediate retry | Attack tests other stolen cards; Twin enters new replacement card. |
| **CP-15** | Amount Camouflage | `normal_amount_test` (5 cards, ₹2.5k)| `normal_multi_cart` (1 card, ₹2.5k) | Typical merchant amounts, 5 attempts | Attack cycles 5 cards; Twin retries single card after OTP failure. |
| **CP-16** | OTP Drop Abandon | `otp_bypass_test` (4 cards, 0 OTP) | `otp_sms_delay` (1 card, 3 timeouts) | 4 attempts without completed auth | Attack abandons for new card; Twin waits for SMS OTP retry. |
| **CP-17** | Midnight Probing | `off_hours_burst` (6 cards, 3 AM) | `insomnia_shopper` (1 card, 3 AM) | 3:00 AM timestamp, 6 attempts | Attack tests batch; Twin browses late night with single card. |
| **CP-18** | Ultra-Patient Drip | `ultra_patient` (3 cards, 21 days) | `monthly_utility` (1 card, 21 days) | 3 attempts separated by 7 days each | Attack uses 3 cards; Twin pays monthly bills on 1 card. |
| **CP-19** | Warm-Up Probe | `warmup_attack` (2 clean, 5 attack) | `frequent_customer` (2 clean, 2 retry)| Account with 2 prior purchases | Attack pivots to card cycling; Twin has genuine billing retry. |
| **CP-20** | Mixed Strategy | `mixed_campaign` (hybrid bot) | `complex_office_order` (group order) | Complex session/IP/device dynamics | Attack is automated distributed probe; Twin is legitimate catering order. |

### 4.3 Evaluation Metric: Counterfactual Pair Ordering Accuracy (CPOA)

For each pair $k \in \{1, \dots, 20\}$, let $S(\text{Attack}_k)$ be the model's predicted risk score for the attack twin, and $S(\text{Legit}_k)$ be the score for its legitimate twin.

$$\text{CPOA} = \frac{1}{K} \sum_{k=1}^K \mathbb{I}\left( S(\text{Attack}_k) > S(\text{Legit}_k) \right)$$

- **Acceptance Threshold**: Model v3 must achieve $\text{CPOA} \ge 90.0\%$ (at least 18 out of 20 pairs correctly ordered).
- **Tie Breaker**: If $S(\text{Attack}_k) == S(\text{Legit}_k)$, it is scored as $0.0$, strictly penalizing models that cannot distinguish causal twins.
