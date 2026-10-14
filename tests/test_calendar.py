from datetime import UTC, date, datetime

import pytest

from dayahead.calendar import delivery_slots, wall_clock


@pytest.mark.parametrize(
    ("day", "slots"),
    [
        (date(2026, 10, 14), 96),
        (date(2026, 3, 29), 92),  # clocks go forward: 02:00-03:00 doesn't exist
        (date(2026, 10, 25), 100),  # clocks go back: 02:00-03:00 happens twice
    ],
)
def test_slot_count_follows_berlin_clock_changes(day, slots):
    assert len(delivery_slots(day)) == slots


def test_day_starts_at_berlin_midnight():
    assert delivery_slots(date(2026, 7, 1))[0] == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)  # CEST
    assert delivery_slots(date(2026, 12, 1))[0] == datetime(2026, 11, 30, 23, 0, tzinfo=UTC)  # CET


def test_fall_back_day_has_the_two_oclock_hour_twice():
    clocks = [wall_clock(ts) for ts in delivery_slots(date(2026, 10, 25))]
    assert clocks.count((2, 0)) == 2
    assert clocks.count((1, 0)) == 1


def test_spring_forward_day_skips_two_oclock():
    clocks = [wall_clock(ts) for ts in delivery_slots(date(2026, 3, 29))]
    assert (2, 0) not in clocks
    assert clocks[8] == (3, 0)
