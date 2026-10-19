"""Event models shared by both services.

Two flavours on purpose:
- `ShipmentEvent`: what the simulator CREATES (it knows the full carrier status).
- `InboundEvent`: what the receiver DECODES from a raw payload (it only knows the raw text
  until it looks the status up in the catalog).
"""

from dataclasses import dataclass
from datetime import datetime

from webhook_simulator.domain.catalog import CarrierStatus


@dataclass(frozen=True, slots=True)
class ShipmentEvent:
    event_id: str
    carrier: str  # carrier slug
    tracking_number: str
    status: CarrierStatus
    occurred_at: datetime  # UTC, whole seconds
    location: str


@dataclass(frozen=True, slots=True)
class InboundEvent:
    event_id: str
    tracking_number: str
    raw_status: str
    occurred_at: datetime  # always timezone-aware UTC
    location: str
