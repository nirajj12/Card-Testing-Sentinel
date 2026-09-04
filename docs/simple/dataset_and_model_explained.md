# Dataset v4.1 and Model v3.1

## Why synthetic sequential data was needed

Public fraud datasets usually describe transactions that have already been
processed. They often include information, such as authorization outcomes,
that Sentinel cannot know before order creation. They also rarely contain the
device, session, timing, and multi-attempt history needed to study card testing.

Dataset v4.1 therefore contains controlled synthetic sequences. This makes it
possible to test causal feature computation and known edge cases. It does not
prove performance on real Razorpay production traffic.

## Dataset size

| Item | Count |
|---|---:|
| Devices | 12,000 |
| Authorization requests | 69,274 |
| Lifecycle events | 179,283 |
| Merchants | 20 |

| Split | Total devices | Attack | Legitimate |
|---|---:|---:|---:|
| Training | 8,500 | 1,530 | 6,970 |
| Held-out validation | 3,500 | 630 | 2,870 |

Some checkouts intentionally have no `customer_id`, as guest checkout is common
in real commerce. The model must still work from device, session, network,
timing, amount, and prior-history signals.

## Why group separation matters

Related devices can belong to the same household, customer, or attack campaign.
If closely related actors appear in both training and validation, a model can
memorize their shared patterns and appear stronger than it is. Dataset v4.1
uses leakage groups so related actors stay on one side of a split or fold.

## Why histories matter

One decline can be normal. A sequence may reveal rapid retries, verified decline
streaks, historical card changes, session changes, IP movement, or successful
checkout history. No attack is required to use every signal, and failure alone
is not treated as fraud.

## What Model v3.1 does

Model v3.1 is a Histogram Gradient Boosting model. It consumes 44 features in a
fixed order and returns a behavioral risk score. Policy v2—not the model—turns
that score and supporting evidence into `ALLOW`, `REVIEW`, or `BLOCK`.

The Replay Lab's “What changed?” view describes observed context between
attempts. It is not SHAP, feature attribution, or proof that one visible value
caused a particular score.

For the full methodology, see [Dataset and Feature Methodology](../dataset.md)
and the [Model v3.1 development report](../../reports/phase_2_6_model_v3_1_development.md).
