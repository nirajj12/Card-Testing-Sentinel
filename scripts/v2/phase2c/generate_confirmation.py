#!/usr/bin/env python3
"""Generate the seed-locked Phase 2C confirmation exactly once."""

import json

from card_testing_sentinel.v2.phase2c.confirmation import write_confirmation_bundle

if __name__ == "__main__":
    print(json.dumps(write_confirmation_bundle(), indent=2, sort_keys=True))
