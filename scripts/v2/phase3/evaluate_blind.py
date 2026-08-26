from card_testing_sentinel.v2.phase3.evaluation import run_blind_once

if __name__ == "__main__":
    result = run_blind_once()
    print(
        f"Phase 3 blind status={result['status']} "
        f"manifest={result['final_manifest_sha256']}"
    )
