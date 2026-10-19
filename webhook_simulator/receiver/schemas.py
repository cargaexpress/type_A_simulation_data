"""Response models. FastAPI uses them to validate output and to build the /docs page."""

from typing import Literal

from pydantic import BaseModel


class IngestResponse(BaseModel):
    status: Literal["stored", "duplicate"]
    carrier: str
    event_id: str


class EventOut(BaseModel):
    id: int  # arrival order; use it as the cursor for incremental exports
    carrier: str
    event_id: str
    tracking_number: str
    raw_status: str
    canonical_status: str | None
    occurred_at: str
    location: str
    content_type: str
    raw_body: str
    delivery_count: int
    first_received_at: str
    last_received_at: str


class CarrierStats(BaseModel):
    unique_events: int
    deliveries: int
    distinct_statuses: int


class StatsOut(BaseModel):
    total_deliveries: int
    unique_events: int
    duplicates: int
    out_of_order: int
    rejected: int
    per_carrier: dict[str, CarrierStats]
