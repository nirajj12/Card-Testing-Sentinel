from card_testing_sentinel.v2.phase3.lifecycle import write_blind_bundle

if __name__ == "__main__":
    manifest = write_blind_bundle()
    print(
        "Phase 3 blind dataset generated once: "
        f"seed={manifest['seed']} "
        f"requests={manifest['structural_validation']['authorization_requests']}"
    )
