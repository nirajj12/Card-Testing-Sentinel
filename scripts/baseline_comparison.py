"""Build-time generation of the frozen baseline comparison artifact.

Answers one question a reviewer will always ask: *why not just block a device
after N attempts?*

Everything here is computed from the already-frozen blind decision rows
(`artifacts/evaluation/blind_event_decisions.csv`). No model is loaded, no
request is rescored, and no policy is evaluated -- the Sentinel column is
read back from the `action` values that were recorded when the blind
evaluation ran. This script is **build-time only**; the running application
never reads the CSV (see `ArtifactRegistry.blind_row_load_count`) and loads
only the small JSON this writes.

Comparison method, applied identically to every approach:

* **Device level.** A device counts as intervened-on if the approach would
  have acted on any one of its authorization requests. Card testing is a
  campaign against a merchant, so the unit that matters is the device, not
  the row.
* **Same denominators.** 300 attacker devices, 1,700 legitimate devices, the
  same frozen rows for all approaches.
* **Same hindsight.** Each approach is evaluated over a device's full
  recorded history. None of them gets a look-ahead the others do not.

The rules-only baseline reads the `rule_score` recorded at decision time,
which was computed from the *same* 44-feature causal engine. That is
deliberately generous to the baseline: it keeps the feature engineering and
removes only the model, so any gap is attributable to the model and policy
rather than to better inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from card_testing_sentinel.common.integrity import sha256_file

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "artifacts/evaluation/blind_event_decisions.csv"
BLIND_METRICS = ROOT / "artifacts/evaluation/blind_metrics.json"
OUTPUT = ROOT / "artifacts/evaluation/baseline_comparison.json"
MANIFEST = ROOT / "artifacts/release_manifest.json"
MANIFEST_SHA = ROOT / "artifacts/release_manifest.sha256"

SCHEMA_VERSION = "card-testing-sentinel-baseline-comparison-1"
MANIFEST_ENTRY = "baseline_comparison"

REQUIRED_COLUMNS = (
    "device_id",
    "request_index",
    "action",
    "rule_score",
    "scenario_tag",
)
REQUEST_COUNT_THRESHOLDS = (4, 5, 7, 10)
RULE_SCORE_THRESHOLDS = (3, 5)
INTERVENTION_ACTIONS = frozenset({"review", "block"})


class ContractError(RuntimeError):
    """The frozen decision rows do not match the contract this script needs."""


def load_devices(path: Path = DECISIONS) -> pd.DataFrame:
    """Collapse the frozen rows to one record per device.

    Fails loudly rather than silently producing a plausible-looking number
    from a file whose shape has changed.
    """
    if not path.is_file():
        raise ContractError(f"frozen blind decisions are missing: {path}")
    frame = pd.read_csv(path)
    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    if missing:
        raise ContractError(f"frozen blind decisions are missing columns: {missing}")
    if frame.empty:
        raise ContractError("frozen blind decisions are empty")

    devices = frame.groupby("device_id").agg(
        requests=("request_index", "max"),
        max_rule_score=("rule_score", "max"),
        scenario_tag=("scenario_tag", "first"),
        intervened=(
            "action",
            lambda actions: bool(set(actions) & INTERVENTION_ACTIONS),
        ),
        blocked=("action", lambda actions: "block" in set(actions)),
    )
    devices["is_attack"] = devices["scenario_tag"].str.startswith("attack_")

    unknown = set(frame["action"].unique()) - {"allow", "review", "block"}
    if unknown:
        raise ContractError(f"frozen decisions contain uncontracted actions: {unknown}")
    if not devices["is_attack"].any() or devices["is_attack"].all():
        raise ContractError("frozen decisions must contain both populations")
    return devices


def _result(
    *,
    identifier: str,
    family: str,
    label: str,
    threshold: int | None,
    flagged: pd.Series,
    devices: pd.DataFrame,
) -> dict:
    attackers = devices["is_attack"]
    attacker_total = int(attackers.sum())
    legitimate_total = int((~attackers).sum())
    detected = int(flagged[attackers].sum())
    false_positives = int(flagged[~attackers].sum())
    return {
        "id": identifier,
        "family": family,
        "label": label,
        "threshold": threshold,
        "attacker_devices": attacker_total,
        "attacker_detected": detected,
        "attacker_recall": detected / attacker_total,
        "legitimate_devices": legitimate_total,
        "legitimate_flagged": false_positives,
        "legitimate_false_positive_rate": false_positives / legitimate_total,
    }


def build_baselines(devices: pd.DataFrame) -> list[dict]:
    """Every approach, computed the same way over the same frozen rows."""
    rows = [
        _result(
            identifier=f"count_ge_{threshold}",
            family="request_count",
            label=f"Count ≥{threshold} requests",
            threshold=threshold,
            flagged=devices["requests"] >= threshold,
            devices=devices,
        )
        for threshold in REQUEST_COUNT_THRESHOLDS
    ]
    rows.extend(
        _result(
            identifier=f"rules_ge_{threshold}",
            family="rules_only",
            label=f"Rules only ≥{threshold} points",
            threshold=threshold,
            flagged=devices["max_rule_score"] >= threshold,
            devices=devices,
        )
        for threshold in RULE_SCORE_THRESHOLDS
    )
    sentinel = _result(
        identifier="sentinel_review_or_higher",
        family="sentinel",
        label="Sentinel (review or higher)",
        threshold=None,
        flagged=devices["intervened"],
        devices=devices,
    )
    sentinel["is_sentinel"] = True
    rows.append(sentinel)
    return rows


def evaluate_dominance(baselines: list[dict]) -> dict:
    """Does any simple baseline beat Sentinel on *both* axes?

    Computed, never assumed. If a future artifact makes a baseline dominant
    this returns `dominated: true` and no claim sentence, so the UI cannot
    keep rendering a statement that has stopped being true.
    """
    sentinel = next(row for row in baselines if row.get("is_sentinel"))
    dominating = [
        row["id"]
        for row in baselines
        if not row.get("is_sentinel")
        and row["attacker_recall"] >= sentinel["attacker_recall"]
        and row["legitimate_false_positive_rate"]
        <= sentinel["legitimate_false_positive_rate"]
        and (
            row["attacker_recall"] > sentinel["attacker_recall"]
            or row["legitimate_false_positive_rate"]
            < sentinel["legitimate_false_positive_rate"]
        )
    ]
    payload = {
        "sentinel_id": sentinel["id"],
        "dominated": bool(dominating),
        "dominating_baselines": dominating,
    }
    if not dominating:
        payload["statement"] = (
            "No tested threshold of either simple baseline beats Sentinel on "
            "both attacker recall and legitimate-user impact."
        )
    return payload


def build_artifact(devices: pd.DataFrame) -> dict:
    baselines = build_baselines(devices)
    attackers = devices["is_attack"]
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "blind_event_decisions_sha256": sha256_file(DECISIONS),
            "blind_metrics_sha256": sha256_file(BLIND_METRICS),
            "devices": int(len(devices)),
            "attacker_devices": int(attackers.sum()),
            "legitimate_devices": int((~attackers).sum()),
        },
        "method": (
            "Device level, same frozen rows and same denominators for every "
            "approach. A device counts as intervened-on if the approach would "
            "have acted on any of its authorization requests. The Sentinel row "
            "is read back from the recorded blind actions; nothing is rescored. "
            "The rules-only baseline uses the rule score recorded at decision "
            "time, computed from the same 44-feature causal engine, so it keeps "
            "the feature engineering and removes only the model."
        ),
        "request_count_thresholds": list(REQUEST_COUNT_THRESHOLDS),
        "rule_score_thresholds": list(RULE_SCORE_THRESHOLDS),
        "baselines": baselines,
        "dominance": evaluate_dominance(baselines),
    }


def update_manifest(artifact_path: Path = OUTPUT) -> str:
    """Register the new artifact using the project's existing mechanism.

    Only the baseline entry is ever written. Model, policy, feature-contract
    and blind-evaluation entries are asserted unchanged, so this can never
    quietly re-bless a tampered frozen artifact.
    """
    manifest = json.loads(MANIFEST.read_text())
    protected = {
        name: entry["sha256"]
        for name, entry in manifest["artifacts"].items()
        if name != MANIFEST_ENTRY
    }
    manifest["artifacts"][MANIFEST_ENTRY] = {
        "path": str(artifact_path.relative_to(ROOT)),
        "sha256": sha256_file(artifact_path),
    }
    still_protected = {
        name: entry["sha256"]
        for name, entry in manifest["artifacts"].items()
        if name != MANIFEST_ENTRY
    }
    if still_protected != protected:
        raise ContractError("refusing to rewrite a protected manifest entry")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    manifest_sha = sha256_file(MANIFEST)
    MANIFEST_SHA.write_text(f"{manifest_sha}  release_manifest.json\n")
    return manifest_sha


def main() -> dict:
    devices = load_devices()
    artifact = build_artifact(devices)
    OUTPUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    manifest_sha = update_manifest()
    return {
        "written": str(OUTPUT.relative_to(ROOT)),
        "schema_version": artifact["schema_version"],
        "baselines": len(artifact["baselines"]),
        "dominated": artifact["dominance"]["dominated"],
        "release_manifest_sha256": manifest_sha,
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
