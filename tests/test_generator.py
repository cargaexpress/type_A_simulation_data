"""RIWI-83: random events per carrier, with realistic journeys."""

import random

from webhook_simulator.domain.catalog import CARRIERS, CARRIERS_BY_SLUG, CanonicalStatus
from webhook_simulator.domain.generator import EventGenerator


def test_timestamps_of_one_shipment_are_chronological(make_generator):
    for shipment in make_generator().new_batch(100):
        times = [e.occurred_at for e in shipment]
        assert times == sorted(times)
        assert len(set(times)) == len(times)


def test_all_events_of_a_shipment_share_carrier_and_tracking(make_generator):
    for shipment in make_generator().new_batch(50):
        assert len({(e.carrier, e.tracking_number) for e in shipment}) == 1
        assert shipment[0].tracking_number.startswith(
            CARRIERS_BY_SLUG[shipment[0].carrier].tracking_prefix
        )


def test_statuses_always_belong_to_the_carrier_that_sent_them(make_generator):
    for shipment in make_generator().new_batch(200):
        profile = CARRIERS_BY_SLUG[shipment[0].carrier]
        assert all(e.status in profile.statuses for e in shipment)


def test_ids_and_tracking_numbers_are_unique(make_generator):
    events = [e for s in make_generator().new_batch(300) for e in s]
    assert len({e.event_id for e in events}) == len(events)
    assert len({s[0].tracking_number for s in make_generator().new_batch(300)}) == 300


def test_every_journey_starts_with_created_and_cancellations_only_happen_early(make_generator):
    for shipment in make_generator().new_batch(300):
        assert shipment[0].status.canonical == CanonicalStatus.CREATED
        for event in shipment[1:]:
            if event.status.cancel:
                assert len(shipment) == 2  # created -> cancelled, nothing else


def test_over_many_shipments_every_carrier_shows_at_least_six_distinct_statuses(make_generator):
    seen = {c.slug: set() for c in CARRIERS}
    for shipment in make_generator().new_batch(600):
        seen[shipment[0].carrier].update(e.status.raw for e in shipment)
    assert all(len(statuses) >= 6 for statuses in seen.values())


def test_same_seed_same_events_different_seed_different_events(make_generator):
    assert make_generator(5).new_batch(10) == make_generator(5).new_batch(10)
    assert make_generator(5).new_batch(10) != make_generator(6).new_batch(10)


def test_it_needs_at_least_one_carrier():
    import pytest

    with pytest.raises(ValueError):
        EventGenerator([], random.Random(1))
