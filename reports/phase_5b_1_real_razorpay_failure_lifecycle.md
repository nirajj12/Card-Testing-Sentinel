# Real Razorpay Failure Lifecycle and Retry Boundary

## Goal

Verify that Card-Testing Sentinel correctly handles real payment failure lifecycles in Razorpay Test Mode without trusting client-side browser events or leaking unverified card attempts into behavioral history.

## Setup

- **Payment Gateway:** Razorpay Standard Checkout (Test Mode)
- **Runtime:** `postblind-v3.1-prototype-runtime` (Model v3.1, 44 features, Policy v2)
- **Storage:** SQLite WAL mode with durable activity logging
- **Trust Boundary:** Cryptographically signed server webhooks (`X-Razorpay-Signature` with HMAC-SHA256)

## What I Tested

- **Checkout Retry Configuration:** Verified that Standard Checkout is initialized with `retry: { enabled: false }` to prevent modal-internal retries from bypassing precheck.
- **Order Creation by Decision:** Verified that only ALLOW decisions create Razorpay Test Mode orders. REVIEW and BLOCK decisions create zero Razorpay orders (`payment_order_not_allowed`).
- **Browser Event Trust Boundary:** Verified that browser-side `payment.failed` callbacks are treated as non-authoritative. Browser failures show an "awaiting signed webhook" status but do not record a trusted decline.
- **Signed Webhook Verification:** Tested delivery and signature verification of real signed Razorpay failure webhooks (`payment.failed`).
- **Behavioral State Updates:** Verified that safe card metadata (network, card type, and distinct card counts) is recorded into behavioral history only after the authoritative signed failure webhook is verified.
- **Current vs. Historical Card Signals:** Verified that the current precheck request does not contain or consume current card information. Subsequent prechecks observe prior trusted outcomes, updating card diversity and decline streak features.
- **Abandoned Checkout Handling:** Verified that abandoned checkouts or payment attempts without a terminal signed webhook are not counted as declines in history.
- **Subsequent Merchant Attempts:** Tested that clicking Pay again creates a new Sentinel precheck with new request and event identifiers under the same shopper/device session.

## Results

| Lifecycle Step | Component Handling | Verified Behavior | Status |
| :--- | :--- | :--- | :--- |
| **1. Precheck Request** | Sentinel `/api/precheck` | Evaluates 44 causal features without current card data; returns decision. | Pass |
| **2. ALLOW Decision** | Backend `/api/razorpay/orders` | Creates exactly one Razorpay Test Mode order; idempotent on repeat. | Pass |
| **3. REVIEW / BLOCK** | Backend `/api/razorpay/orders` | Order creation suppressed (HTTP 409 `payment_order_not_allowed`); 0 orders created. | Pass |
| **4. Modal Failure** | Frontend Checkout Modal | Razorpay modal shows failure without internal retries (`retry.enabled = false`). | Pass |
| **5. Browser Callback** | Frontend `ondismiss` / handler | Displays "awaiting signed webhook"; zero changes to backend behavioral history. | Pass |
| **6. Signed Webhook** | Backend `/api/webhooks/razorpay` | Validates HMAC signature; records trusted failed payment and safe card metadata. | Pass |
| **7. Re-Attempt Precheck** | Sentinel `/api/precheck` | Next attempt observes prior verified decline; updates 7-day card diversity and retry features. | Pass |

### Test Suite Evidence

- **Frontend Tests:** 69 passed (31 legacy tests + 38 React component tests).
- **Targeted Razorpay Backend Tests:** 12 passed.
- **Full Python Test Suite:** 277 passed, 262 deselected, 0 failed, ~90% coverage.
- **Frontend Production Build:** Passed (2,105 modules transformed).
- **Release and Runtime Verifiers:** Both `verify_release.py` and `verify_runtime_v3_1.py` passed.

## What the Results Mean

1. **Strict Gateway Trust Boundary:** The backend never trusts browser events to update risk state. Only an HMAC-verified Razorpay server webhook can transition an attempt to a trusted decline.
2. **True Causal Independence:** Precheck runs before payment details exist, preventing circular dependence on the card being tested. Safe card metadata becomes visible only to *future* requests after gateway confirmation.
3. **Model vs. Integration Separation:** Incomplete detection on certain evasive attack patterns reflects model generalization under distribution shift, not a broken payment integration or lost webhook state.

## Limitations

- **Test Mode Only:** All validation used Razorpay Test Mode credentials and synthetic or test card profiles. This is not a production deployment.
- **Webhook Delivery Dependency:** Historical state update requires timely webhook arrival from Razorpay. Delayed or dropped webhooks require queue reconciliation in production.
- **No Production Traffic:** Evaluated on simulated test scenarios, not real live merchant checkout traffic.

## Reproducibility

- **Webhook Endpoint:** `POST /api/webhooks/razorpay`
- **Verifier Commands:**
  ```bash
  python scripts/verify_release.py
  python scripts/verify_runtime_v3_1.py
  ```
- **Test Command:**
  ```bash
  pytest tests/integration/test_razorpay_checkout.py tests/integration/test_razorpay_webhooks.py
  ```
