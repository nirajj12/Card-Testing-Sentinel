"""Validate the immutable v4 dataset contract and write its JSON report."""

import argparse
import logging
import sys
from pathlib import Path

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.exceptions import (
    ConfigurationError,
    DataValidationError,
)
from card_testing_sentinel.common.logging import configure_logging
from card_testing_sentinel.data.validation import (
    inspect_frozen_dataset,
    require_valid_dataset,
    write_validation_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "base.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"application YAML path (default: {DEFAULT_CONFIG})",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        settings = load_config(args.config)
        configure_logging(settings)
        result = inspect_frozen_dataset(settings)
        write_validation_report(result.report, settings.frozen_dataset.report_path)
        require_valid_dataset(result)
    except ConfigurationError as exc:
        print(f"Configuration failed: {exc}", file=sys.stderr)
        return 2
    except DataValidationError as exc:
        logging.getLogger(__name__).error("Dataset validation failed: %s", exc)
        print(f"Dataset validation failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Frozen dataset valid: "
        f"{result.report['total_checks_passed']} checks passed, "
        f"report={settings.frozen_dataset.report_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
