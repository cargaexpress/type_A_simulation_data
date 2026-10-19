"""Formats layer: the 5 carrier message formats, both directions.

    encode()  -> used by the simulator to build what a carrier would send
    decode()  -> used by the receiver to understand it

Keeping both sides together makes it trivial to prove they agree (see tests/test_formats.py).
"""

from webhook_simulator.domain.catalog import PayloadFormat
from webhook_simulator.domain.models import ShipmentEvent
from webhook_simulator.formats.decoders import PayloadError, decode
from webhook_simulator.formats.encoders import ENCODERS, EncodedRequest


def encode(payload_format: PayloadFormat, event: ShipmentEvent) -> EncodedRequest:
    return ENCODERS[payload_format](event)


__all__ = ["EncodedRequest", "PayloadError", "decode", "encode"]
