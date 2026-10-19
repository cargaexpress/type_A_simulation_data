"""Command-line entry point of the simulator (wired up by both `__main__` files)."""

import asyncio
import contextlib
import json
import logging
import signal
import sys

import httpx
from pydantic import ValidationError

from webhook_simulator.simulator.config import SimulatorSettings, load_settings
from webhook_simulator.simulator.runner import run
from webhook_simulator.simulator.sender import USER_AGENT, DryRunSender, HttpSender
from webhook_simulator.simulator.stats import RunStats

log = logging.getLogger("webhook_simulator")


def _install_stop_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):  # `docker stop` sends SIGTERM
        with contextlib.suppress(NotImplementedError):  # Windows has no loop signal handlers
            loop.add_signal_handler(sig, stop.set)


async def _run_simulation(settings: SimulatorSettings, stop: asyncio.Event) -> RunStats:
    if settings.dry_run:
        sender = DryRunSender(sys.stdout, settings.target_url_template)
        return await run(settings, sender, stop=stop)
    async with httpx.AsyncClient(
        timeout=settings.request_timeout, headers={"User-Agent": USER_AGENT}
    ) as client:
        sender = HttpSender(client, settings.target_url_template)
        return await run(settings, sender, stop=stop)


async def _main(settings: SimulatorSettings) -> int:
    stop = asyncio.Event()
    _install_stop_handlers(stop)

    log.info(
        "simulator started: carriers=%s target=%s rate=%s/s duplicates=%.0f%% "
        "out_of_order=%.0f%% seed=%s%s",
        settings.carriers, settings.target_url_template, settings.rate,
        settings.duplicate_rate * 100, settings.out_of_order_rate * 100, settings.seed,
        " (dry-run)" if settings.dry_run else "",
    )  # fmt: skip
    stats = await _run_simulation(settings, stop)
    log.info("final summary: %s", json.dumps(stats.as_dict(), ensure_ascii=False))

    # With a message limit and not a single successful delivery, exit with an error code
    # so docker / CI can tell something is wrong (usually: the receiver isn't reachable).
    if settings.max_events and not settings.dry_run and stats.delivered == 0:
        return 1
    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request is noise
    try:
        settings = load_settings()
    except ValidationError as exc:
        for error in exc.errors():
            where = ".".join(str(part) for part in error["loc"])
            message = error["msg"].removeprefix("Value error, ")
            print(f"invalid setting {where}: {message}", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(_main(settings)))
