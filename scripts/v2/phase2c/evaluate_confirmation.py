#!/usr/bin/env python3
"""Run the single permitted Phase 2C confirmation evaluation."""

import json

from card_testing_sentinel.v2.phase2c.evaluation import run_confirmation

if __name__ == "__main__":
    print(json.dumps(run_confirmation(), indent=2, sort_keys=True))
