#!/usr/bin/env python3
import json

from card_testing_sentinel.v2.policy.evaluation import run_validation_policy_phase

if __name__ == "__main__":
    print(json.dumps(run_validation_policy_phase(), indent=2, sort_keys=True))
