"""`python -m webhook_simulator.receiver` starts the receiver API."""

import logging
import sys

import uvicorn

from webhook_simulator.receiver.api import create_app
from webhook_simulator.receiver.config import ReceiverSettings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    settings = ReceiverSettings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=settings.access_log,
        log_config=None,  # keep OUR logging format instead of uvicorn's own
    )


if __name__ == "__main__":
    main()
