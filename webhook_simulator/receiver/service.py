"""Ingestion use case: raw HTTP body in, stored event out.

1. find the carrier           (unknown slug  -> UnknownCarrier)
2. decode its own format      (broken body   -> park it in rejected_events, InvalidPayload)
3. translate status to ours   (unknown status is fine: stored with canonical = NULL)
4. store idempotently         (repeat of a known event -> "duplicate", not an error)
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from webhook_simulator.domain.catalog import CARRIERS_BY_SLUG
from webhook_simulator.formats import PayloadError, decode
from webhook_simulator.receiver.repository import EventRepository

log = logging.getLogger("webhook_simulator.receiver")


class UnknownCarrier(LookupError):
    pass


class InvalidPayload(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IngestResult:
    outcome: Literal["stored", "duplicate"]
    carrier: str
    event_id: str


def _utc_iso(moment: datetime) -> str:
    """ISO-8601 UTC with milliseconds and a trailing Z, e.g. 2026-10-13T12:00:00.000Z."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class IngestService:
    def __init__(
        self,
        repository: EventRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))  # injectable for tests

    def ingest(self, carrier_slug: str, content_type: str, body: bytes) -> IngestResult:
        profile = CARRIERS_BY_SLUG.get(carrier_slug)
        if profile is None:
            raise UnknownCarrier(carrier_slug)

        received_at = _utc_iso(self._clock())
        raw_body = body.decode("utf-8", errors="replace")

        try:
            event = decode(profile.payload_format, body)
        except PayloadError as exc:
            self._repository.save_rejected(
                carrier=carrier_slug,
                content_type=content_type,
                raw_body=raw_body,
                reason=str(exc),
                received_at=received_at,
            )
            log.warning("rejected %s payload: %s", carrier_slug, exc)
            raise InvalidPayload(str(exc)) from exc

        canonical = profile.canonical_for(event.raw_status)
        if canonical is None:
            log.warning("%s sent an unmapped status: %r", carrier_slug, event.raw_status)

        is_new = self._repository.save_event(
            carrier=carrier_slug,
            event_id=event.event_id,
            tracking_number=event.tracking_number,
            raw_status=event.raw_status,
            canonical_status=canonical.value if canonical else None,
            occurred_at=_utc_iso(event.occurred_at),
            location=event.location,
            content_type=content_type,
            raw_body=raw_body,
            received_at=received_at,
        )
        return IngestResult("stored" if is_new else "duplicate", carrier_slug, event.event_id)
