"""Train and validate the approved Phase 3 offline baselines."""

import argparse
import sys
from pathlib import Path

import yaml

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.exceptions import SentinelError
from card_testing_sentinel.common.logging import configure_logging
from card_testing_sentinel.modeling.data import (
    frozen_checksums,
    load_train_validation_views,
)
from card_testing_sentinel.modeling.training import run_training

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/base.yaml")
    parser.add_argument(
        "--training-config", type=Path, default=ROOT / "configs/training.yaml"
    )
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--figure-dir", type=Path)
    parser.add_argument("--mlflow-dir", type=Path)
    args = parser.parse_args()
    try:
        settings = load_config(args.config)
        configure_logging(settings)
        config = yaml.safe_load(args.training_config.read_text(encoding="utf-8"))
        artifacts = (args.artifacts_dir or settings.paths.artifacts).resolve()
        train, validation = load_train_validation_views(settings)
        result = run_training(
            train,
            validation,
            config=config,
            seed=settings.random_seed,
            checksums=frozen_checksums(settings),
            dataset_version=settings.frozen_dataset.version,
            eda_path=artifacts / "metrics/training_eda_summary.json",
            artifacts_dir=artifacts,
            figure_dir=(
                args.figure_dir or settings.paths.reports / "figures"
            ).resolve(),
            mlflow_dir=(args.mlflow_dir or settings.paths.mlflow).resolve(),
        )
    except (OSError, KeyError, ValueError, SentinelError) as exc:
        print(f"Baseline training failed: {exc}", file=sys.stderr)
        return 1
    print(f"Phase 3 validation complete: champion={result['champion']}")
    print("Test split untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
