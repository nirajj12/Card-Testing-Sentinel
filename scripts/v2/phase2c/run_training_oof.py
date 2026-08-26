#!/usr/bin/env python3
"""Run Phase 2C policy development on training devices only."""

import json

from card_testing_sentinel.v2.phase2c.development import run_training_oof

if __name__ == "__main__":
    print(json.dumps(run_training_oof(), indent=2, sort_keys=True))
