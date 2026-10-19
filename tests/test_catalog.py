"""RIWI-84: each carrier has its own catalog of at least 6 custom statuses."""

import pytest

from webhook_simulator.domain.catalog import (
    CARRIERS,
    CARRIERS_BY_SLUG,
    CanonicalStatus,
    PayloadFormat,
)


def test_there_are_exactly_five_carriers_with_different_formats():
    assert len(CARRIERS) == 5
    assert {c.payload_format for c in CARRIERS} == set(PayloadFormat)


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
def test_every_carrier_has_at_least_six_statuses(carrier):
    assert len(carrier.statuses) >= 6
    assert len({s.raw for s in carrier.statuses}) == len(carrier.statuses)  # no repeats


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
def test_every_canonical_status_is_reachable_and_there_is_a_cancel_status(carrier):
    reachable = {s.canonical for s in carrier.statuses}
    assert reachable == set(CanonicalStatus)
    assert any(s.cancel for s in carrier.statuses)


def test_canonical_for_translates_known_statuses_and_ignores_unknown_ones():
    gamma = CARRIERS_BY_SLUG["gamma"]
    assert gamma.canonical_for("En reparto") == CanonicalStatus.OUT_FOR_DELIVERY
    assert gamma.canonical_for("Perdida o dañada") == CanonicalStatus.LOST_OR_DAMAGED
    assert gamma.canonical_for("nope") is None


def test_statuses_for_can_separate_cancellations_from_other_exceptions():
    alpha = CARRIERS_BY_SLUG["alpha"]
    plain = {s.raw for s in alpha.statuses_for(CanonicalStatus.EXCEPTION)}
    cancel = {s.raw for s in alpha.statuses_for(CanonicalStatus.EXCEPTION, cancel=True)}
    assert plain == {"DELIVERY_ATTEMPT_FAILED", "HELD_AT_CUSTOMS"}
    assert cancel == {"CANCELLED"}
