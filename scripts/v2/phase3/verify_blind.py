from card_testing_sentinel.v2.phase3.evaluation import verify_final_manifest
from card_testing_sentinel.v2.phase3.lifecycle import (
    refuse_if_scoring_accessed,
    verify_lifecycle,
)

if __name__ == "__main__":
    verify_lifecycle(root=__import__("pathlib").Path.cwd(), state="post_scoring")
    verify_final_manifest()
    try:
        refuse_if_scoring_accessed()
    except PermissionError as error:
        print(f"Phase 3 verified; second run refused: {error}")
    else:
        raise RuntimeError("second blind scoring invocation was not refused")
