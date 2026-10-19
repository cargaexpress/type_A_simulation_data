"""Simulator configuration: SIM_* environment variables, overridable from the command line.

Priority (highest first): command-line flags > SIM_* env vars > defaults below.
Every flag has a matching variable, e.g. `--max-events 10` <-> `SIM_MAX_EVENTS=10`.
"""

from collections.abc import Sequence

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from webhook_simulator.domain.catalog import CARRIERS, CARRIERS_BY_SLUG
from webhook_simulator.domain.chaos import ChaosConfig

DEFAULT_TARGET = "http://localhost:9000/webhooks/{carrier}"


class SimulatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIM_",
        env_ignore_empty=True,  # `SIM_SEED=` (empty, as docker compose passes it) means "unset"
        frozen=True,
    )

    target_url_template: str = Field(
        DEFAULT_TARGET,
        description="Destination URL; {carrier} becomes alpha, beta, gamma, delta or epsilon",
    )
    carriers: str = Field(
        ",".join(c.slug for c in CARRIERS),
        description="Comma-separated carriers to simulate (default: all 5)",
    )
    rate: float = Field(5.0, ge=0, description="Messages per second (0 = no pauses)")
    shipments_per_batch: int = Field(
        20, ge=1, description="Shipments generated and mixed together in each batch"
    )
    max_events: int = Field(0, ge=0, description="Stop after N messages (0 = run forever)")
    duplicate_rate: float = Field(
        0.10, ge=0, le=1, description="Probability (0-1) of re-sending an identical event"
    )
    out_of_order_rate: float = Field(
        0.10, ge=0, le=1,
        description="Probability (0-1) that an event arrives after a later one of its shipment",
    )  # fmt: skip
    duplicate_max_delay: int = Field(
        5, ge=0, description="A duplicate arrives at most this many messages after the original"
    )
    seed: int | None = Field(None, description="Seed to replay the exact same simulation")
    dry_run: bool = Field(False, description="Print what would be sent, but send nothing")
    request_timeout: float = Field(5.0, gt=0, description="Max seconds to wait per request")

    @field_validator("target_url_template")
    @classmethod
    def _needs_carrier_placeholder(cls, value: str) -> str:
        if "{carrier}" not in value:
            raise ValueError("must contain the {carrier} placeholder")
        return value

    @field_validator("carriers")
    @classmethod
    def _known_carriers(cls, value: str) -> str:
        slugs = [part.strip().lower() for part in value.split(",") if part.strip()]
        unknown = [slug for slug in slugs if slug not in CARRIERS_BY_SLUG]
        if unknown or not slugs:
            valid = ", ".join(CARRIERS_BY_SLUG)
            raise ValueError(f"unknown carriers {unknown or '(none given)'}; valid ones: {valid}")
        return ",".join(slugs)

    @property
    def carrier_slugs(self) -> tuple[str, ...]:
        return tuple(self.carriers.split(","))

    @property
    def chaos(self) -> ChaosConfig:
        return ChaosConfig(self.duplicate_rate, self.out_of_order_rate, self.duplicate_max_delay)


def load_settings(argv: Sequence[str] | None = None) -> SimulatorSettings:
    """Build settings from env vars + CLI flags (`argv=None` reads the real command line)."""
    return SimulatorSettings(
        _cli_parse_args=True if argv is None else list(argv),
        _cli_kebab_case=True,  # --max-events instead of --max_events
        _cli_implicit_flags=True,  # --dry-run / --no-dry-run
        _cli_prog_name="webhook_simulator",
    )
