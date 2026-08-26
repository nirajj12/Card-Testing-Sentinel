from card_testing_sentinel.v2.phase3.lifecycle import build_pre_access_freeze

if __name__ == "__main__":
    path, digest = build_pre_access_freeze()
    print(f"Phase 3 pre-access freeze: {path} sha256={digest}")
