"""Record the SHA-256 freeze record for the blind benchmark.

Run in three stages:

    python scripts/freeze_blind_benchmark.py --stage development
    python scripts/freeze_blind_benchmark.py --stage blind
    python scripts/freeze_blind_benchmark.py --stage dataset

Stage 1 pins the frozen model, policy and feature contract *before* any
blind-generation code is written. Stage 2 pins the blind specification,
config and generator source *before* the blind set is generated. Stage 3 pins
the generated benchmark itself, *after* generation and validation both pass
and still before any model touches it.

Nothing here reads a model prediction or a metric -- it only hashes bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts/evaluation/blind_freeze_manifest.json"

#: Current benchmark revision. v1.0 was generated and failed its own
#: pre-evaluation validation; no performance number was ever observed for it,
#: so v1.1 is a correction of an unevaluated benchmark, not a second look at a
#: held-out set. The v1.0 freeze record is preserved in `revision_history`.
BLIND_VERSION = "v1.1"

DEVELOPMENT_FILES = {
    "model_sha256": "artifacts/model/risk_model.joblib",
    "model_metadata_sha256": "artifacts/model/metadata.json",
    "feature_contract_sha256": "artifacts/model/feature_contract.json",
    "policy_sha256": "artifacts/policy/operational_policy.json",
    "training_config_sha256": "configs/training.yaml",
    "policy_config_sha256": "configs/policy.yaml",
    "feature_config_sha256": "configs/features.yaml",
    "development_manifest_sha256": "data/generated/development/manifest.json",
}

#: Why each superseded revision was replaced, recorded in `revision_history`.
REVISION_REASONS = {
    "v1": (
        "v1.0 was frozen and generated, then FAILED its own pre-evaluation "
        "validation. The objective generation defects: merchant kinds were "
        "sampled with replacement so flash_sale, travel and the unseen "
        "ticketing_events archetype had zero merchants; scenarios whose "
        "declared merchant kinds were all absent silently fell back to the "
        "full merchant pool; and the attack fraction was applied per actor, "
        "producing 0.291 attack devices against a configured 0.20; and "
        "`window.days` named a span it did not bound. The "
        "legitimate decline rate of 0.4179 also breached the benchmark's own "
        "plausibility gate of 0.40. NO model score, policy decision, recall, "
        "precision, PR-AUC, FPR or any other blind performance result was "
        "observed for v1.0; it was never evaluated and was never consumed."
    ),
}

BLIND_FILES = {
    "blind_spec_sha256": "docs/blind_spec.md",
    "blind_config_sha256": "configs/blind.yaml",
}

#: Stage 3, run only after generation and validation both succeed. From this
#: point the generated benchmark itself is immutable: `--verify` fails if any
#: of these bytes change, so a silent regeneration cannot pass unnoticed.
DATASET_FILES = {
    "raw_events_sha256": "data/generated/blind/raw_events.csv",
    "labels_sha256": "data/generated/blind/labels.csv",
    "features_sha256": "data/generated/blind/features.csv",
    "manifest_sha256": "data/generated/blind/manifest.json",
}

#: Hashed together as one bundle, so any edit to the generation path is visible.
#: v1.1 adds `merchants.py` and `scenarios.py`: they are part of the generation
#: path, and v1.0's merchant-allocation defect lived in `merchants.py` where
#: the bundle could not see it.
BLIND_GENERATOR_SOURCES = (
    "src/card_testing_sentinel/ml/blind_generator.py",
    "src/card_testing_sentinel/ml/primitives.py",
    "src/card_testing_sentinel/ml/merchants.py",
    "src/card_testing_sentinel/ml/scenarios.py",
    "pipelines/generate_blind.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_hash(paths: tuple[str, ...]) -> str:
    """Order-stable hash over several source files."""
    digest = hashlib.sha256()
    for name in sorted(paths):
        digest.update(name.encode())
        digest.update(sha256_file(ROOT / name).encode())
    return digest.hexdigest()


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return {
        "blind_version": BLIND_VERSION,
        "blind_evaluated": False,
        "consumed": False,
    }


def freeze(stage: str) -> dict:
    manifest = load_manifest()
    files = {
        "development": DEVELOPMENT_FILES,
        "blind": BLIND_FILES,
        "dataset": DATASET_FILES,
    }[stage]
    missing = [name for name in files.values() if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit(f"cannot freeze {stage}: missing {missing}")

    section = {key: sha256_file(ROOT / name) for key, name in files.items()}
    section["files"] = dict(files)
    if stage == "blind":
        missing_sources = [
            name for name in BLIND_GENERATOR_SOURCES if not (ROOT / name).is_file()
        ]
        if missing_sources:
            raise SystemExit(f"cannot freeze blind: missing {missing_sources}")
        section["blind_generator_sha256"] = bundle_hash(BLIND_GENERATOR_SOURCES)
        section["blind_generator_sources"] = list(BLIND_GENERATOR_SOURCES)
    section["frozen_utc"] = datetime.now(UTC).isoformat()

    # A superseded revision is archived, never erased. The record that v1.0
    # existed and failed pre-evaluation validation is part of the benchmark's
    # honesty: it shows how many times the specification was touched.
    previous = manifest.get("blind_version")
    if previous and previous != BLIND_VERSION:
        history = manifest.setdefault("revision_history", [])
        if not any(entry["blind_version"] == previous for entry in history):
            history.append(
                {
                    "blind_version": previous,
                    "superseded_utc": datetime.now(UTC).isoformat(),
                    "blind_evaluated": bool(manifest.get("blind_evaluated")),
                    "consumed": bool(manifest.get("consumed")),
                    "development": manifest.get("development"),
                    "blind": manifest.get("blind"),
                    "reason": REVISION_REASONS.get(previous, "superseded"),
                }
            )

    manifest[stage] = section
    manifest["blind_version"] = BLIND_VERSION
    manifest["blind_evaluated"] = False
    manifest.setdefault("consumed", False)
    manifest["note"] = (
        "Frozen dependencies for the blind benchmark. Once any blind model or "
        "policy metric is observed this benchmark version is CONSUMED: the "
        "frozen files must not be edited, and a changed model or policy "
        "requires a new blind version with a new seed and spec revision."
    )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify() -> list[str]:
    """Return the list of frozen dependencies whose bytes have changed."""
    manifest = load_manifest()
    drift: list[str] = []
    for stage in ("development", "blind", "dataset"):
        section = manifest.get(stage)
        if not section:
            continue
        for key, name in section.get("files", {}).items():
            path = ROOT / name
            if not path.is_file():
                drift.append(f"{stage}.{key}: {name} is missing")
            elif sha256_file(path) != section[key]:
                drift.append(f"{stage}.{key}: {name} changed since the freeze")
        if "blind_generator_sha256" in section:
            actual = bundle_hash(tuple(section["blind_generator_sources"]))
            if actual != section["blind_generator_sha256"]:
                drift.append("blind.blind_generator_sha256: generator source changed")
    return drift


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=("development", "blind", "dataset"), required=False
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        problems = verify()
        print(json.dumps({"drift": problems, "ok": not problems}, indent=2))
        raise SystemExit(1 if problems else 0)
    if not args.stage:
        raise SystemExit("pass --stage development|blind|dataset or --verify")
    result = freeze(args.stage)
    print(json.dumps(result[args.stage], indent=2, sort_keys=True))
