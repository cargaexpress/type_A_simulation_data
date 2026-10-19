"""The 5 carrier formats: golden samples, encode/decode round trip, and hostile input."""

import json
from datetime import UTC, datetime

import pytest

from webhook_simulator.domain.catalog import CARRIERS, CARRIERS_BY_SLUG, PayloadFormat
from webhook_simulator.formats import PayloadError, decode, encode

WHEN = datetime(2026, 10, 13, 12, 30, 15, tzinfo=UTC)

# Hand-written payloads, exactly as each carrier would send them. These do NOT go through
# our encoders, so they prove the decoders understand the real thing.
GOLDEN = {
    PayloadFormat.JSON_FLAT: b'{"event_id":"e1","tracking_number":"ALP1","status":"IN_TRANSIT",'
    b'"occurred_at":"2026-10-13T12:30:15Z","location":"Cali"}',
    PayloadFormat.JSON_NESTED: b'{"eventId":"e1","shipment":{"trackingId":"ALP1"},'
    b'"event":{"code":"300","occurredAtEpochMs":1791894615000},"hub":"Cali"}',
    PayloadFormat.JSON_ES: '{"id_evento":"e1","guia":"ALP1","estado":"En tránsito",'
    '"fecha":"2026-10-13T07:30:15-05:00","ciudad":"Cali"}'.encode(),
    PayloadFormat.XML: b'<?xml version="1.0"?><ShipmentEvent id="e1"><Tracking>ALP1</Tracking>'
    b"<Status>TRN</Status><Timestamp>20261013T123015Z</Timestamp><Location>Cali</Location>"
    b"</ShipmentEvent>",
    PayloadFormat.FORM: b"evt=e1&awb=ALP1&state=Departed+origin+facility&ts=1791894615&city=Cali",
}


@pytest.mark.parametrize("payload_format", list(PayloadFormat))
def test_decoders_understand_golden_payloads(payload_format):
    event = decode(payload_format, GOLDEN[payload_format])
    assert (event.event_id, event.tracking_number, event.location) == ("e1", "ALP1", "Cali")
    assert event.occurred_at == WHEN  # every carrier's clock ends up as the same UTC instant


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
def test_encode_then_decode_gives_back_the_same_event(carrier, make_generator):
    generator = make_generator(3)
    for _ in range(25):
        for event in generator.new_shipment(carrier):
            decoded = decode(carrier.payload_format, encode(carrier.payload_format, event).body)
            assert decoded.event_id == event.event_id
            assert decoded.tracking_number == event.tracking_number
            assert decoded.raw_status == event.status.raw
            assert decoded.occurred_at == event.occurred_at
            assert decoded.location == event.location


def test_each_format_declares_the_right_content_type(make_generator):
    event = make_generator().new_shipment()[0]
    expected = {
        PayloadFormat.JSON_FLAT: "application/json",
        PayloadFormat.JSON_NESTED: "application/json",
        PayloadFormat.JSON_ES: "application/json; charset=utf-8",
        PayloadFormat.XML: "application/xml",
        PayloadFormat.FORM: "application/x-www-form-urlencoded",
    }
    for payload_format, content_type in expected.items():
        assert encode(payload_format, event).content_type == content_type


def test_gamma_sends_local_colombian_time(make_generator):
    event = make_generator().new_shipment(CARRIERS_BY_SLUG["gamma"])[0]
    sent = json.loads(encode(PayloadFormat.JSON_ES, event).body)["fecha"]
    assert sent.endswith("-05:00")


@pytest.mark.parametrize("payload_format", list(PayloadFormat))
@pytest.mark.parametrize("garbage", [b"", b"not a payload", b"\xff\xfe\x00", b"[]", b"{}"])
def test_garbage_is_always_a_payload_error_never_a_crash(payload_format, garbage):
    with pytest.raises(PayloadError):
        decode(payload_format, garbage)


def test_a_timestamp_without_timezone_is_refused():
    body = GOLDEN[PayloadFormat.JSON_FLAT].replace(b"2026-10-13T12:30:15Z", b"2026-10-13T12:30:15")
    with pytest.raises(PayloadError, match="timezone"):
        decode(PayloadFormat.JSON_FLAT, body)


def test_missing_and_empty_fields_are_named_in_the_error():
    body = GOLDEN[PayloadFormat.JSON_FLAT].replace(b'"IN_TRANSIT"', b'"  "')
    with pytest.raises(PayloadError, match="status"):
        decode(PayloadFormat.JSON_FLAT, body)


def test_oversized_fields_are_refused():
    body = GOLDEN[PayloadFormat.JSON_FLAT].replace(b'"Cali"', b'"' + b"x" * 500 + b'"')
    with pytest.raises(PayloadError, match="too long"):
        decode(PayloadFormat.JSON_FLAT, body)


def test_xml_entity_bombs_are_blocked():
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "lol"><!ENTITY b "&a;&a;&a;&a;">]>'
        b'<ShipmentEvent id="&b;"><Tracking>1</Tracking></ShipmentEvent>'
    )
    with pytest.raises(PayloadError):
        decode(PayloadFormat.XML, bomb)


def test_nested_json_epoch_must_be_an_integer():
    body = GOLDEN[PayloadFormat.JSON_NESTED].replace(b"1791894615000", b'"soon"')
    with pytest.raises(PayloadError, match="integer"):
        decode(PayloadFormat.JSON_NESTED, body)
