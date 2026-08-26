#!/usr/bin/env python3
"""Freeze Phase 2C development before confirmation generation."""

from card_testing_sentinel.v2.phase2c.confirmation import build_development_freeze

if __name__ == "__main__":
    freeze_path, digest = build_development_freeze()
    print(f"{freeze_path}: {digest}")
