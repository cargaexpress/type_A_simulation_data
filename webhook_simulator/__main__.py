import asyncio
import json
import logging
import signal
import sys

from webhook_simulator.config import parse_settings
from webhook_simulator.runner import run


async def _main() -> int:
    settings = parse_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):  # docker stop envía SIGTERM
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    logging.getLogger("webhook_simulator").info(
        "simulador iniciado: transportadoras=%s destino=%s rate=%s/s duplicados=%.0f%% fuera_de_orden=%.0f%% semilla=%s%s",
        ",".join(settings.carriers), settings.target_url_template, settings.rate,
        settings.duplicate_rate * 100, settings.out_of_order_rate * 100, settings.seed,
        " (dry-run)" if settings.dry_run else "",
    )
    stats = await run(settings, stop=stop)
    logging.getLogger("webhook_simulator").info("resumen final: %s", json.dumps(stats.as_dict(), ensure_ascii=False))
    # Con un límite de mensajes y sin una sola entrega correcta, avisa con código de error.
    if settings.max_events and not settings.dry_run and stats.delivered == 0:
        return 1
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # un INFO por mensaje inunda el log
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
