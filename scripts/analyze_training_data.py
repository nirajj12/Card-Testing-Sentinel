"""Run mandatory exploratory analysis on training authorizations only."""

import argparse
import sys
from pathlib import Path

import yaml

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.exceptions import SentinelError
from card_testing_sentinel.common.logging import configure_logging
from card_testing_sentinel.evaluation.eda import run_training_eda
from card_testing_sentinel.modeling.data import frozen_checksums, load_training_view

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/base.yaml")
    parser.add_argument(
        "--training-config", type=Path, default=ROOT / "configs/training.yaml"
    )
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--figure-dir", type=Path)
    args = parser.parse_args()
    try:
        settings = load_config(args.config)
        configure_logging(settings)
        options = yaml.safe_load(args.training_config.read_text(encoding="utf-8"))
        view = load_training_view(settings)
        artifacts = (args.artifacts_dir or settings.paths.artifacts).resolve()
        summary = run_training_eda(
            view,
            checksums=frozen_checksums(settings),
            dataset_version=settings.frozen_dataset.version,
            metrics_dir=artifacts / "metrics",
            figure_dir=(
                args.figure_dir or settings.paths.reports / "figures"
            ).resolve(),
            near_constant_share=float(options["near_constant_share"]),
            shortcut_limit=float(options["shortcut_f1_limit"]),
        )
    except (OSError, KeyError, ValueError, SentinelError) as exc:
        print(f"Training EDA failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Training EDA passed: {summary['authorization_rows']} authorizations, "
        f"{summary['unique_devices']} devices, zero validation/test rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
