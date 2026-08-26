# Limitations and production boundary

- Data generation and evaluation are synthetic; results do not establish
  performance on Razorpay or other merchant traffic.
- Nobody was detected within the first three attempts. Median first review was
  attempt 5 and median first block was attempt 7.
- Twenty-nine of 300 blind attackers were never detected. Patient and evasive
  behavior remains harder than burst behavior.
- The risk score is not a guaranteed fraud probability.
- The offline potentially-preventable count assumes later attempts would stop;
  it is not observed savings or causal fraud prevention.
- One process-wide lock and local SQLite prioritize causal correctness and
  demonstrability, not horizontal scale or high availability.
- The prototype has no merchant authentication, authorization, rate limiting,
  tenant isolation, secret service, distributed idempotency, durable stream,
  drift monitor or human-review feedback loop.

A production implementation needs real merchant validation, a transactional
partitioned state store, durable event transport, multiple workers, audited
secret management, service authentication, retention and migration controls,
operational monitoring, drift detection and a safe staged rollout.
