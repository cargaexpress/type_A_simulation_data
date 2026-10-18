"""RIWI-83: generador de eventos aleatorios por transportadora."""
from collections import Counter

import pytest

from webhook_simulator.catalog import CARRIERS, CARRIERS_BY_SLUG
from webhook_simulator.generator import EventGenerator
import random


def test_misma_semilla_mismos_eventos(make_generator):
    a = make_generator(5).new_batch(10)
    b = make_generator(5).new_batch(10)
    c = make_generator(6).new_batch(10)
    assert a == b
    assert a != c


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
def test_envio_empieza_creado_y_tiempos_crecen(make_generator, carrier):
    gen = make_generator(3)
    for _ in range(50):
        events = gen.new_shipment(carrier)
        assert events[0].status.canonical == "CREATED"
        assert len({e.tracking_number for e in events}) == 1
        assert events[0].tracking_number.startswith(carrier.tracking_prefix)
        times = [e.occurred_at for e in events]
        assert times == sorted(times) and len(set(times)) == len(times)
        assert all(e.occurred_at.microsecond == 0 for e in events)
        assert all(e.status in carrier.statuses and e.carrier == carrier.slug for e in events)


def test_ids_y_guias_unicos(make_generator):
    events = [e for s in make_generator(2).new_batch(200) for e in s]
    assert len({e.event_id for e in events}) == len(events)
    assert len({e.tracking_number for e in events}) == 200


def test_estados_variados_por_transportadora(make_generator):
    gen = make_generator(11)
    seen = {c.slug: Counter() for c in CARRIERS}
    for s in gen.new_batch(1500):
        for e in s:
            seen[e.carrier][e.status.raw] += 1
    for carrier in CARRIERS:
        assert len(seen[carrier.slug]) >= 6, carrier.slug
        # se alcanzan todos los estados del catálogo
        assert set(seen[carrier.slug]) == {s.raw for s in carrier.statuses}


def test_recorridos_incluyen_excepcion_devolucion_perdida_y_cancelacion(make_generator):
    finals = Counter()
    for s in make_generator(4).new_batch(1000):
        finals[s[-1].status.canonical] += 1
    assert {"DELIVERED", "RETURNED", "LOST_OR_DAMAGED", "EXCEPTION"} <= set(finals)


def test_sin_perfiles_falla():
    with pytest.raises(ValueError):
        EventGenerator([], random.Random(1))
