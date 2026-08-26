#!/usr/bin/env python3
import json

from card_testing_sentinel.v2.policy.blocked import write_blocked_report

if __name__ == "__main__":
    print(json.dumps(write_blocked_report(), indent=2, sort_keys=True))
