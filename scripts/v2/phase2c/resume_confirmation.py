#!/usr/bin/env python3
"""Resume the existing unscored Phase 2C confirmation attempt."""

import json

from card_testing_sentinel.v2.phase2c.resumed_evaluation import (
    run_resumed_confirmation,
)

if __name__ == "__main__":
    print(json.dumps(run_resumed_confirmation(), indent=2, sort_keys=True))
