from pathlib import Path

from card_testing_sentinel.ml.training import train_development_model

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    result = train_development_model(
        ROOT / "data/development/events_with_features.csv",
        ROOT / "configs/training.yaml",
        ROOT / "artifacts/development/training",
    )
    print(result)
