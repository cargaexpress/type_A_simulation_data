"""Receiver configuration (RECEIVER_* environment variables)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReceiverSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECEIVER_", env_ignore_empty=True, frozen=True)

    host: str = "0.0.0.0"
    port: int = Field(9000, ge=1, le=65535)
    db_path: str = Field("data/events.db", description="SQLite file; docker mounts it at /data")
    max_body_bytes: int = Field(1_000_000, ge=1, description="Webhook bodies above this get a 413")
    access_log: bool = Field(False, description="One log line per request (noisy at 5 msg/s)")
