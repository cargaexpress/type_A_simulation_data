"""RIWI-83 / criterio: eventos con formatos diferentes."""
import pytest

from tests.helpers import decode
from webhook_simulator.catalog import CARRIERS, CARRIERS_BY_SLUG
from webhook_simulator.formats import FORMATS, encode


def _events(make_generator, slug, n=30):
    gen = make_generator(7)
    out = []
    while len(out) < n:
        out += gen.new_shipment(CARRIERS_BY_SLUG[slug])
    return out


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
def test_ida_y_vuelta_conserva_el_evento(make_generator, carrier):
    for ev in _events(make_generator, carrier.slug):
        req = encode(carrier.payload_format, ev)
        d = decode(carrier.payload_format, req.body)
        assert d == dict(event_id=ev.event_id, tracking=ev.tracking_number, status=ev.status.raw,
                         occurred_at=ev.occurred_at, location=ev.location)


def test_los_cinco_formatos_son_realmente_distintos(make_generator):
    ev = make_generator().new_shipment(CARRIERS_BY_SLUG["alpha"])[0]
    bodies = {name: encode(name, ev) for name in FORMATS}
    assert len({r.body for r in bodies.values()}) == 5
    assert bodies["xml"].content_type == "application/xml"
    assert bodies["form"].content_type == "application/x-www-form-urlencoded"
    assert all(bodies[n].content_type.startswith("application/json") for n in ("json_flat", "json_nested", "json_es"))
    assert bodies["xml"].body.startswith(b"<?xml")


def test_cada_carrier_usa_un_formato_registrado():
    assert {c.payload_format for c in CARRIERS} == set(FORMATS)
