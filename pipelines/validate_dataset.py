from pathlib import Path

from card_testing_sentinel.ml.validation import validate_dataset

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    print(validate_dataset(ROOT / "data/development"))
