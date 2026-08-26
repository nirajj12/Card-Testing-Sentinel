#!/usr/bin/env python3
"""Create the append-only Phase 2C replay/environment correction chain."""

import json

from card_testing_sentinel.v2.phase2c.amendment import create_correction_chain

if __name__ == "__main__":
    print(json.dumps(create_correction_chain(), indent=2, sort_keys=True))
