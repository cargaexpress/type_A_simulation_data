"""RIWI-85: duplicados y eventos fuera de orden, configurables."""
import random
from collections import Counter

import pytest

from webhook_simulator.chaos import ChaosConfig, plan_deliveries, summarize


def _batch(make_generator, n=40, seed=1):
    return make_generator(seed).new_batch(n)


def _plan(make_generator, dup, ooo, seed=9, delay=5, n=40):
    return plan_deliveries(_batch(make_generator, n), ChaosConfig(dup, ooo, delay), random.Random(seed))


def test_sin_caos_todo_llega_en_orden_y_sin_duplicados(make_generator):
    plan = _plan(make_generator, 0, 0)
    stats = summarize(plan)
    assert stats.duplicates == 0 and stats.out_of_order == 0
    assert stats.total == stats.unique == sum(len(s) for s in _batch(make_generator))


def test_duplicados_al_100_por_ciento(make_generator):
    plan = _plan(make_generator, 1, 0)
    stats = summarize(plan)
    assert stats.duplicates == stats.unique
    counts = Counter(d.event.event_id for d in plan)
    assert set(counts.values()) == {2}


def test_duplicado_es_identico_byte_a_byte_y_llega_despues(make_generator):
    plan = _plan(make_generator, 0.5, 0, delay=3)
    first_pos = {}
    for pos, d in enumerate(plan):
        if not d.duplicate:
            first_pos[d.event.event_id] = pos
        else:
            original = first_pos[d.event.event_id]  # el original siempre llega antes
            assert pos > original


def test_retraso_cero_pone_el_duplicado_justo_despues(make_generator):
    plan = _plan(make_generator, 1, 0, delay=0)
    for i, d in enumerate(plan):
        if d.duplicate:
            assert plan[i - 1].event == d.event and not plan[i - 1].duplicate


def test_desorden_al_100_por_ciento(make_generator):
    stats = summarize(_plan(make_generator, 0, 1))
    assert stats.out_of_order > 0


def test_el_desorden_conserva_los_mismos_eventos(make_generator):
    base = {e.event_id for s in _batch(make_generator) for e in s}
    plan = _plan(make_generator, 0.3, 0.5)
    assert {d.event.event_id for d in plan} == base


def test_sin_desorden_cada_envio_conserva_su_orden(make_generator):
    plan = _plan(make_generator, 0.4, 0)
    last = {}
    for d in plan:
        if d.duplicate:
            continue
        t = d.event.occurred_at
        assert last.get(d.event.tracking_number, t) <= t
        last[d.event.tracking_number] = t


def test_tasas_intermedias_producen_algo_de_cada_cosa(make_generator):
    stats = summarize(_plan(make_generator, 0.2, 0.2, n=200))
    assert 0 < stats.duplicates < stats.unique
    assert stats.out_of_order > 0


def test_mas_tasa_mas_desorden(make_generator):
    low = summarize(_plan(make_generator, 0, 0.05, n=200)).out_of_order
    high = summarize(_plan(make_generator, 0, 0.8, n=200)).out_of_order
    assert high > low


def test_reproducible_con_la_misma_semilla(make_generator):
    assert _plan(make_generator, 0.3, 0.3, seed=4) == _plan(make_generator, 0.3, 0.3, seed=4)
    assert _plan(make_generator, 0.3, 0.3, seed=4) != _plan(make_generator, 0.3, 0.3, seed=5)


@pytest.mark.parametrize("kwargs", [
    {"duplicate_rate": -0.1}, {"duplicate_rate": 1.1},
    {"out_of_order_rate": -1}, {"out_of_order_rate": 2},
    {"duplicate_max_delay": -1},
])
def test_configuracion_invalida(kwargs):
    with pytest.raises(ValueError):
        ChaosConfig(**kwargs)
