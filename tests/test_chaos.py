"""RIWI-85: configurable duplicates and out-of-order events."""

import random
from collections import Counter

import pytest

from webhook_simulator.domain.chaos import ChaosConfig, plan_deliveries, summarize


def _batch(make_generator, n=40, seed=1):
    return make_generator(seed).new_batch(n)


def _plan(make_generator, dup, ooo, seed=9, delay=5, n=40):
    return plan_deliveries(
        _batch(make_generator, n), ChaosConfig(dup, ooo, delay), random.Random(seed)
    )


def test_without_chaos_everything_arrives_in_order_and_once(make_generator):
    stats = summarize(_plan(make_generator, 0, 0))
    assert stats.duplicates == 0 and stats.out_of_order == 0
    assert stats.total == stats.unique == sum(len(s) for s in _batch(make_generator))


def test_duplicates_at_100_percent_double_every_event(make_generator):
    plan = _plan(make_generator, 1, 0)
    stats = summarize(plan)
    assert stats.duplicates == stats.unique
    assert set(Counter(d.event.event_id for d in plan).values()) == {2}


def test_a_duplicate_is_the_same_event_and_always_arrives_after_the_original(make_generator):
    first_position = {}
    for position, delivery in enumerate(_plan(make_generator, 0.5, 0, delay=3)):
        if not delivery.duplicate:
            first_position[delivery.event.event_id] = position
        else:
            assert position > first_position[delivery.event.event_id]


def test_zero_delay_puts_the_duplicate_right_after_the_original(make_generator):
    plan = _plan(make_generator, 1, 0, delay=0)
    for i, delivery in enumerate(plan):
        if delivery.duplicate:
            assert plan[i - 1].event == delivery.event and not plan[i - 1].duplicate


def test_out_of_order_at_100_percent_really_reorders(make_generator):
    assert summarize(_plan(make_generator, 0, 1)).out_of_order > 0


def test_disorder_keeps_exactly_the_same_events(make_generator):
    base = {e.event_id for s in _batch(make_generator) for e in s}
    assert {d.event.event_id for d in _plan(make_generator, 0.3, 0.5)} == base


def test_without_disorder_each_shipment_keeps_its_own_order(make_generator):
    last = {}
    for delivery in _plan(make_generator, 0.4, 0):
        if delivery.duplicate:
            continue
        moment = delivery.event.occurred_at
        assert last.get(delivery.event.tracking_number, moment) <= moment
        last[delivery.event.tracking_number] = moment


def test_in_between_rates_produce_a_bit_of_everything(make_generator):
    stats = summarize(_plan(make_generator, 0.2, 0.2, n=200))
    assert 0 < stats.duplicates < stats.unique
    assert stats.out_of_order > 0


def test_a_higher_rate_means_more_disorder(make_generator):
    low = summarize(_plan(make_generator, 0, 0.05, n=200)).out_of_order
    high = summarize(_plan(make_generator, 0, 0.8, n=200)).out_of_order
    assert high > low


def test_same_seed_same_plan(make_generator):
    assert _plan(make_generator, 0.3, 0.3, seed=4) == _plan(make_generator, 0.3, 0.3, seed=4)
    assert _plan(make_generator, 0.3, 0.3, seed=4) != _plan(make_generator, 0.3, 0.3, seed=5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duplicate_rate": -0.1},
        {"duplicate_rate": 1.1},
        {"out_of_order_rate": -1},
        {"out_of_order_rate": 2},
        {"duplicate_max_delay": -1},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ChaosConfig(**kwargs)
