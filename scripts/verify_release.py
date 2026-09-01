"""Release verification.

Disabled during the rules_only migration phase: there is no frozen model
or evaluation bundle to verify yet. It returns once Dataset V2 training
produces signed artifacts again.
"""

from pathlib import Path

from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    validate_feature_contract,
)

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    validate_feature_contract()
    print(
        {
            "status": "rules_only_phase",
            "reason": "no frozen model or blind evaluation artifacts to verify yet",
            "feature_contract_valid": True,
            "feature_count": len(MODEL_FEATURES),
        }
    )
