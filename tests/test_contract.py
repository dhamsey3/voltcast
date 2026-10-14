from datetime import date, timedelta

import pytest

from dayahead.calendar import delivery_slots
from dayahead.contract import ContractViolation, check_day, is_complete

DAY = date(2026, 10, 14)


def good_points():
    return [(ts, 100.0) for ts in delivery_slots(DAY)]


def test_complete_valid_day_passes():
    points = good_points()
    assert is_complete(DAY, points)
    check_day(DAY, points)


def test_unpublished_slots_mean_incomplete_not_invalid():
    points = good_points()
    points[-1] = (points[-1][0], None)
    assert not is_complete(DAY, points)


def test_duplicate_slots_violate_contract():
    points = good_points()
    with pytest.raises(ContractViolation, match="duplicate"):
        check_day(DAY, [*points, points[0]])


def test_off_grid_timestamps_violate_contract():
    points = good_points()
    points.append((points[0][0] + timedelta(minutes=7), 100.0))
    with pytest.raises(ContractViolation, match="off the 15-minute grid"):
        check_day(DAY, points)


@pytest.mark.parametrize("price", [-500.01, 4000.01])
def test_prices_beyond_auction_limits_violate_contract(price):
    points = good_points()
    points[10] = (points[10][0], price)
    with pytest.raises(ContractViolation, match="outside"):
        check_day(DAY, points)


def test_auction_limits_themselves_are_valid():
    points = good_points()
    points[0] = (points[0][0], -500.0)
    points[1] = (points[1][0], 4000.0)
    check_day(DAY, points)
