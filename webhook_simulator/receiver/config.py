"""Receiver configuration (RECEIVER_* environment variables)."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReceiverSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECEIVER_", env_ignore_empty=True, frozen=True)

    host: str = "0.0.0.0"
    port: int = Field(
        9000,
        validation_alias=AliasChoices("RECEIVER_PORT", "PORT"),
        ge=1,
        le=65535,
    )
    db_path: str = Field("data/events.db", description="SQLite file; used if database_url is unset")
    database_url: str | None = Field(
        None,
        validation_alias=AliasChoices("RECEIVER_DATABASE_URL", "DATABASE_URL"),
        description="PostgreSQL / Supabase connection URL. If set, takes precedence over db_path.",
    )
    retention_days: int = Field(
        3, ge=0, description="Auto-delete events older than N days to save space (0 = keep forever)"
    )
    auto_simulate: bool = Field(
        False,
        validation_alias=AliasChoices("RECEIVER_AUTO_SIMULATE", "AUTO_SIMULATE"),
        description="Run event simulator automatically and continuously in the background",
    )
    sim_rate: float = Field(
        0.5,
        validation_alias=AliasChoices("RECEIVER_SIM_RATE", "SIM_RATE"),
        ge=0.01,
        description="Events per second when auto_simulate is True (default: 1 event every 2s)",
    )
    max_body_bytes: int = Field(1_000_000, ge=1, description="Webhook bodies above this get a 413")
    access_log: bool = Field(False, description="One log line per request (noisy at 5 msg/s)")

    @property
    def target_database(self) -> str:
        """Return the active database target: database_url if provided, otherwise db_path."""
        return self.database_url or self.db_path
