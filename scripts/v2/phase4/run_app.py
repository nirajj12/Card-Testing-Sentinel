import uvicorn

from card_testing_sentinel.v2.phase4.app import create_app

if __name__ == "__main__":
    application = create_app()
    config = application.state.phase4.config
    uvicorn.run(
        application,
        host=str(config["host"]),
        port=int(config["port"]),
        log_level=str(config["log_level"]).lower(),
    )
