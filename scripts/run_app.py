import uvicorn

from card_testing_sentinel.app import create_app

if __name__ == "__main__":
    application = create_app()
    config = application.state.runtime.config
    uvicorn.run(
        application,
        host=str(config["host"]),
        port=int(config["port"]),
        log_level=str(config["log_level"]).lower(),
    )
