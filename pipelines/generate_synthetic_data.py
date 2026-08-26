from pathlib import Path

import yaml

from card_testing_sentinel.ml.generation import write_development_bundle

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    config = yaml.safe_load((ROOT / "configs/training.yaml").read_text())
    result = write_development_bundle(
        config["synthetic_data"], ROOT / "data/development"
    )
    print(result)
