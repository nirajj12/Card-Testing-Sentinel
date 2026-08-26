from pathlib import Path

from card_testing_sentinel.common.integrity import sha256_file, verify_manifest
from card_testing_sentinel.modeling.registry import ArtifactRegistry

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    manifest_path = ROOT / "artifacts/release_manifest.json"
    manifest_sha256 = sha256_file(manifest_path)
    recorded_sha256 = (
        (ROOT / "artifacts/release_manifest.sha256").read_text().split()[0]
    )
    if manifest_sha256 != recorded_sha256:
        raise SystemExit("release manifest checksum mismatch")
    manifest = verify_manifest(ROOT, manifest_path)
    registry = ArtifactRegistry.load(ROOT)
    print(
        {
            "status": "release_verified",
            "manifest_version": manifest["manifest_version"],
            "manifest_sha256": manifest_sha256,
            "feature_count": registry.system_summary()["feature_count"],
            "blind_rows_rescored": False,
        }
    )
