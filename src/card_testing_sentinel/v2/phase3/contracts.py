"""Frozen paths and contracts for the Phase 3 blind challenge."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BLIND_SEED = 20260828
POLICY_ID = "phase2c_002"
POLICY_SHA256 = "9afeba2df176c87287e86ff0402ef96b58e9386608d003b5702986be02b6ae95"
REPLACEMENT_FREEZE_SHA256 = (
    "f0b473ac81f356b1f6d114491148ac25d2edbaac4a96b2309d6ab5c034a2177b"
)
EXECUTION_AMENDMENT_SHA256 = (
    "a026fce117025926d00272f4c4cb90581b4cebdaac4d0aab8ecf03992ac6d44f"
)
PHASE2C_FINAL_MANIFEST_SHA256 = (
    "611b022a674478a869a4599921984717a32c4d7cb0de36969946889b50f0b6b1"
)

CONFIG_PATH = Path("configs/v2/phase3/blind.yaml")
DATA_PATH = Path("data/v2/phase3/blind")
ARTIFACT_PATH = Path("artifacts/v2/phase3/blind")
REPORT_PATH = Path("reports/v2/phase3/blind/phase_closeout.md")
FREEZE_PATH = ARTIFACT_PATH / "pre_access_freeze.json"
LEDGER_PATH = ARTIFACT_PATH / "access_ledger.json"
DATASET_MANIFEST_PATH = ARTIFACT_PATH / "dataset_manifest.json"

SCENARIO_COUNTS = {
    "normal_standard": 1200,
    "normal_bad_luck": 100,
    "flash_standard": 300,
    "flash_hard_retry": 100,
    "attack_burst": 120,
    "attack_evasive": 90,
    "attack_patient": 90,
}
SAFETY_ALLOWANCES = {
    "overall_legitimate": {"review_or_higher": 51, "block": 17},
    "normal_standard": {"review_or_higher": 24, "block": 6},
    "normal_bad_luck": {"review_or_higher": 5, "block": 2},
    "flash_standard": {"review_or_higher": 15, "block": 9},
    "flash_hard_retry": {"review_or_higher": 10, "block": 5},
}
EFFECTIVENESS_TARGETS = {
    "overall_review_or_higher": 0.70,
    "overall_block": 0.50,
    "burst_review_or_higher": 0.90,
    "evasive_review_or_higher": 0.50,
    "patient_review_or_higher": 0.40,
}
FINAL_STATUSES = {
    "blind_completed_passed",
    "blind_completed_failed",
    "blocked_pre_access",
    "blocked_post_generation_pre_scoring",
    "blind_execution_failed",
}
RESULT_FILES = (
    "allow_all_parity.json",
    "final_blind_metrics.json",
    "final_blind_event_decisions.csv",
    "final_blind_device_summary.csv",
    "runtime.json",
    "final_hash_manifest.json",
    "final_hash_manifest.sha256",
)
