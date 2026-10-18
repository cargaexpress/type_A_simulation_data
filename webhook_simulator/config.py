"""Configuración: variables de entorno SIM_* con opciones de línea de comandos que las reemplazan."""

import argparse
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from webhook_simulator.catalog import CARRIERS, CARRIERS_BY_SLUG
from webhook_simulator.chaos import ChaosConfig

DEFAULT_TARGET = "http://localhost:9000/webhooks/{carrier}"


@dataclass(frozen=True)
class Settings:
    target_url_template: str = DEFAULT_TARGET
    carriers: tuple[str, ...] = field(default_factory=lambda: tuple(c.slug for c in CARRIERS))
    rate: float = 5.0  # mensajes por segundo; 0 = sin pausas
    shipments_per_batch: int = 20
    max_events: int = 0  # 0 = sin límite
    duplicate_rate: float = 0.10
    out_of_order_rate: float = 0.10
    duplicate_max_delay: int = 5
    seed: int | None = None
    dry_run: bool = False
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if "{carrier}" not in self.target_url_template:
            raise ValueError("target_url_template debe incluir {carrier}")
        unknown = [slug for slug in self.carriers if slug not in CARRIERS_BY_SLUG]
        if unknown or not self.carriers:
            valid = ", ".join(CARRIERS_BY_SLUG)
            raise ValueError(f"Transportadoras inválidas {unknown or '(vacío)'}; válidas: {valid}")
        if self.rate < 0:
            raise ValueError("rate no puede ser negativo")
        if self.shipments_per_batch < 1:
            raise ValueError("shipments_per_batch debe ser al menos 1")
        if self.max_events < 0:
            raise ValueError("max_events no puede ser negativo")
        if self.timeout <= 0:
            raise ValueError("timeout debe ser mayor que 0")
        self.chaos  # valida las tasas

    @property
    def chaos(self) -> ChaosConfig:
        return ChaosConfig(self.duplicate_rate, self.out_of_order_rate, self.duplicate_max_delay)


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def parse_settings(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    base = Settings()  # valores por defecto

    def get(name: str, default, cast):
        raw = env.get(f"SIM_{name}")
        return default if raw is None or raw == "" else cast(raw)

    parser = argparse.ArgumentParser(
        prog="webhook_simulator",
        description="Simulador de webhooks de 5 transportadoras Tipo A (cada opción tiene su variable SIM_*).",
    )
    parser.add_argument("--target-url-template", default=get("TARGET_URL_TEMPLATE", base.target_url_template, str),
                        help="URL de destino; {carrier} se reemplaza por alpha, beta, gamma, delta o epsilon")
    parser.add_argument("--carriers", default=get("CARRIERS", ",".join(base.carriers), str),
                        help="transportadoras a simular, separadas por coma (por defecto, las 5)")
    parser.add_argument("--rate", type=float, default=get("RATE", base.rate, float),
                        help="mensajes por segundo (0 = sin pausas)")
    parser.add_argument("--shipments-per-batch", type=int, default=get("SHIPMENTS_PER_BATCH", base.shipments_per_batch, int),
                        help="envíos que se generan y mezclan en cada lote")
    parser.add_argument("--max-events", type=int, default=get("MAX_EVENTS", base.max_events, int),
                        help="detenerse tras enviar este número de mensajes (0 = sin límite)")
    parser.add_argument("--duplicate-rate", type=float, default=get("DUPLICATE_RATE", base.duplicate_rate, float),
                        help="probabilidad (0 a 1) de reenviar un evento idéntico")
    parser.add_argument("--out-of-order-rate", type=float, default=get("OUT_OF_ORDER_RATE", base.out_of_order_rate, float),
                        help="probabilidad (0 a 1) de que un evento llegue después de uno posterior de su envío")
    parser.add_argument("--duplicate-max-delay", type=int, default=get("DUPLICATE_MAX_DELAY", base.duplicate_max_delay, int),
                        help="un duplicado llega, como máximo, tantos mensajes después del original")
    parser.add_argument("--seed", type=int, default=get("SEED", base.seed, int),
                        help="semilla para repetir exactamente la misma simulación")
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=get("DRY_RUN", base.dry_run, _env_bool),
                        help="mostrar lo que se enviaría, sin enviar nada")
    parser.add_argument("--timeout", type=float, default=get("REQUEST_TIMEOUT", base.timeout, float),
                        help="segundos máximos de espera por cada envío")
    args = parser.parse_args(argv)

    try:
        return Settings(
            target_url_template=args.target_url_template,
            carriers=tuple(s.strip().lower() for s in args.carriers.split(",") if s.strip()),
            rate=args.rate,
            shipments_per_batch=args.shipments_per_batch,
            max_events=args.max_events,
            duplicate_rate=args.duplicate_rate,
            out_of_order_rate=args.out_of_order_rate,
            duplicate_max_delay=args.duplicate_max_delay,
            seed=args.seed,
            dry_run=args.dry_run,
            timeout=args.timeout,
        )
    except ValueError as exc:
        parser.error(str(exc))
