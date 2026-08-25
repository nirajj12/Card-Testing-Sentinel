from pathlib import Path

from card_testing_sentinel.v2.data.generator import write_development_bundle

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    manifest = write_development_bundle(
        ROOT / "configs/v2/generation.yaml", ROOT / "data/v2/development"
    )
    print(f"Generated V2 development bundle: {manifest['counts']}")
