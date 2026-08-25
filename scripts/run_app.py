"""Run the local judge-facing application."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "card_testing_sentinel.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )
