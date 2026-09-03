# Limitations and production boundary

- Data generation and evaluation are synthetic; results do not establish
  performance on Razorpay or other merchant traffic.
- The active PBRSS-v1 shifted stress result is `MIXED`: attack REVIEW+ reached
  96.40%, but 20.72% of legitimate devices also reached REVIEW+.
- PBRSS-v1 hard-blocked 59.12% of attack devices and 0.16% of legitimate
  devices. Distributed and single-attempt attacks remain difficult to block.
- Historical Blind v2 evaluated Model v2 and received a `WEAK` verdict. It is
  preserved as historical evidence, not presented as the active result.
- The risk score is not a guaranteed fraud probability.
- Economic scenario values are illustrative merchant assumptions, not observed
  savings or causal fraud prevention.
- Razorpay integration is Test Mode only. Browser callbacks are not trusted as
  payment outcomes; authoritative live history requires a verified, correlated
  gateway webhook.
- One process-wide lock and local SQLite prioritize causal correctness and
  demonstrability, not horizontal scale or high availability.
- The prototype has no merchant authentication, authorization, rate limiting,
  tenant isolation, secret service, distributed idempotency, durable stream,
  drift monitor or human-review feedback loop.

A production implementation needs real merchant validation, a transactional
partitioned state store, durable event transport, multiple workers, audited
secret management, service authentication, retention and migration controls,
operational monitoring, drift detection and a safe staged rollout.
