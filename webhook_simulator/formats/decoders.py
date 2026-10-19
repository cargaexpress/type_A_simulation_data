"""Decoders: turn a raw carrier payload back into an `InboundEvent`.

This is the receiver's side of the story. A decoder is STRICT about what it needs (ids,
status, a timestamp WITH a timezone) and raises `PayloadError` for anything else, so the
receiver can park bad payloads instead of silently storing garbage.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as SafeET  # blocks entity-expansion bombs and friends

from webhook_simulator.domain.catalog import PayloadFormat
from webhook_simulator.domain.models import InboundEvent

MAX_FIELD_LENGTH = 200
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class PayloadError(ValueError):
    """The payload can't be understood (bad syntax, missing field, bad timestamp...)."""


# ---------------------------------------------------------------- small validation helpers
def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"missing or empty field: {field}")
    if len(value) > MAX_FIELD_LENGTH:
        raise PayloadError(f"field too long: {field}")
    return value


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:  # refusing to guess a timezone is safer than guessing wrong
        raise PayloadError("timestamp has no timezone")
    return moment.astimezone(UTC)


def _json_object(body: bytes) -> dict:
    data = json.loads(body)
    if not isinstance(data, dict):
        raise PayloadError("JSON payload must be an object")
    return data


def _epoch(value: object, unit: str, field: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadError(f"{field} must be an integer")
    return EPOCH + timedelta(**{unit: value})  # exact math, no float rounding


# ------------------------------------------------------------------------ one per format
def json_flat(body: bytes) -> InboundEvent:
    d = _json_object(body)
    return InboundEvent(
        event_id=_text(d.get("event_id"), "event_id"),
        tracking_number=_text(d.get("tracking_number"), "tracking_number"),
        raw_status=_text(d.get("status"), "status"),
        occurred_at=_utc(datetime.fromisoformat(_text(d.get("occurred_at"), "occurred_at"))),
        location=_text(d.get("location"), "location"),
    )


def json_nested(body: bytes) -> InboundEvent:
    d = _json_object(body)
    shipment, event = d.get("shipment"), d.get("event")
    if not isinstance(shipment, dict) or not isinstance(event, dict):
        raise PayloadError("missing 'shipment' or 'event' object")
    return InboundEvent(
        event_id=_text(d.get("eventId"), "eventId"),
        tracking_number=_text(shipment.get("trackingId"), "shipment.trackingId"),
        raw_status=_text(event.get("code"), "event.code"),
        occurred_at=_epoch(event.get("occurredAtEpochMs"), "milliseconds", "occurredAtEpochMs"),
        location=_text(d.get("hub"), "hub"),
    )


def json_es(body: bytes) -> InboundEvent:
    d = _json_object(body)
    return InboundEvent(
        event_id=_text(d.get("id_evento"), "id_evento"),
        tracking_number=_text(d.get("guia"), "guia"),
        raw_status=_text(d.get("estado"), "estado"),
        occurred_at=_utc(datetime.fromisoformat(_text(d.get("fecha"), "fecha"))),
        location=_text(d.get("ciudad"), "ciudad"),
    )


def xml(body: bytes) -> InboundEvent:
    root = SafeET.fromstring(body)
    if root.tag != "ShipmentEvent":
        raise PayloadError("root element must be <ShipmentEvent>")
    stamp = _text(root.findtext("Timestamp"), "Timestamp")
    return InboundEvent(
        event_id=_text(root.get("id"), "id"),
        tracking_number=_text(root.findtext("Tracking"), "Tracking"),
        raw_status=_text(root.findtext("Status"), "Status"),
        occurred_at=datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
        location=_text(root.findtext("Location"), "Location"),
    )


def form(body: bytes) -> InboundEvent:
    raw = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
    fields = {key: values[0] for key, values in raw.items()}
    try:
        seconds = int(fields.get("ts", ""))
    except ValueError as exc:
        raise PayloadError("ts must be an integer") from exc
    return InboundEvent(
        event_id=_text(fields.get("evt"), "evt"),
        tracking_number=_text(fields.get("awb"), "awb"),
        raw_status=_text(fields.get("state"), "state"),
        occurred_at=_epoch(seconds, "seconds", "ts"),
        location=_text(fields.get("city"), "city"),
    )


DECODERS: dict[PayloadFormat, Callable[[bytes], InboundEvent]] = {
    PayloadFormat.JSON_FLAT: json_flat,
    PayloadFormat.JSON_NESTED: json_nested,
    PayloadFormat.JSON_ES: json_es,
    PayloadFormat.XML: xml,
    PayloadFormat.FORM: form,
}

# Everything the stdlib parsers can throw at us on garbage input. Anything else is a real bug
# and is allowed to blow up loudly.
_PARSING_ERRORS = (ValueError, TypeError, KeyError, OverflowError, OSError, ParseError)


def decode(payload_format: PayloadFormat, body: bytes) -> InboundEvent:
    """Decode `body` or raise PayloadError, no matter how it is broken."""
    try:
        return DECODERS[payload_format](body)
    except PayloadError:
        raise
    except _PARSING_ERRORS as exc:
        raise PayloadError(f"malformed {payload_format.value} payload: {exc}") from exc
