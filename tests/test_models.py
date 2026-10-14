from datetime import date, timedelta

from voltcast.calendar import delivery_slots, wall_clock
from voltcast.models import MODELS, seasonal_naive


def history_for(day, price=lambda ts: float(wall_clock(ts)[0] * 100 + wall_clock(ts)[1])):
    """Price encodes the Berlin wall clock (08:15 -> 815) so alignment is visible."""
    return {day: [(ts, price(ts)) for ts in delivery_slots(day)]}


def test_same_slot_last_week():
    target = date(2026, 10, 16)
    forecast = seasonal_naive(target, history_for(target - timedelta(days=7)), 7)
    assert len(forecast) == 96
    assert [v for _, v in forecast][:3] == [0.0, 15.0, 30.0]
    assert all(v == wall_clock(ts)[0] * 100 + wall_clock(ts)[1] for ts, v in forecast)


def test_target_with_repeated_hour_reuses_source_hour_for_both():
    target = date(2026, 10, 25)  # 100 slots
    forecast = seasonal_naive(target, history_for(date(2026, 10, 18)), 7)
    assert len(forecast) == 100
    assert [v for ts, v in forecast if wall_clock(ts) == (2, 0)] == [200.0, 200.0]


def test_source_with_repeated_hour_is_averaged():
    source = date(2026, 10, 25)
    first_two = iter([1.0, 3.0])
    prices = {ts: (next(first_two) if wall_clock(ts) == (2, 0) else 50.0) for ts in delivery_slots(source)}
    forecast = seasonal_naive(date(2026, 11, 1), {source: list(prices.items())}, 7)
    assert len(forecast) == 96
    assert dict((wall_clock(ts), v) for ts, v in forecast)[(2, 0)] == 2.0


def test_source_missing_hour_falls_back_to_previous_hour():
    forecast = seasonal_naive(date(2026, 4, 5), history_for(date(2026, 3, 29)), 7)
    assert len(forecast) == 96
    assert dict((wall_clock(ts), v) for ts, v in forecast)[(2, 15)] == 115.0


def test_target_missing_hour_has_92_slots():
    forecast = seasonal_naive(date(2026, 3, 29), history_for(date(2026, 3, 22)), 7)
    assert len(forecast) == 92


def test_models_only_read_the_past():
    target = date(2026, 10, 16)
    for model in MODELS.values():
        assert all(day < target for day in model.input_days(target))
