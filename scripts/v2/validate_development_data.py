from pathlib import Path

from card_testing_sentinel.v2.data.validation import write_validation_reports

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    result = write_validation_reports(ROOT)
    print(f"V2 development validation: {result['status']}")
