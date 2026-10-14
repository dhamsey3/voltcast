"""Forecasting models.

Phase 1 ships deliberately simple models (docs/adr/0003). Each model declares
which past delivery days it reads, so the pipeline can check they exist,
record them for lineage, and refuse to look at anything published after the
forecast was made.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from voltcast.calendar import delivery_slots, wall_clock

Prices = list[tuple[datetime, float]]
History = Mapping[date, Prices]


@dataclass(frozen=True)
class Model:
    name: str
    version: str
    description: str
    input_days: Callable[[date], list[date]]
    predict: Callable[[date, History], Prices]


def seasonal_naive(target: date, history: History, lag_days: int) -> Prices:
    """Copy the price of the same Berlin wall-clock slot ``lag_days`` earlier.

    Aligning on wall-clock time (not UTC) keeps 08:00 mapped to 08:00 across a
    DST change. Edge cases: if the source day had the clock-change hour twice
    (fall-back), the two values are averaged; if it skipped the hour
    (spring-forward), the previous hour's value is used.
    """
    by_clock: dict[tuple[int, int], list[float]] = defaultdict(list)
    for ts, value in history[target - timedelta(days=lag_days)]:
        by_clock[wall_clock(ts)].append(value)

    forecast = []
    for slot in delivery_slots(target):
        hour, minute = wall_clock(slot)
        values = by_clock.get((hour, minute)) or by_clock.get((hour - 1, minute))
        if not values:
            raise ValueError(f"no source price for {hour:02d}:{minute:02d} on {target - timedelta(days=lag_days)}")
        forecast.append((slot, sum(values) / len(values)))
    return forecast


def _lagged(lag_days: int) -> Callable[[date], list[date]]:
    return lambda target: [target - timedelta(days=lag_days)]


MODELS: dict[str, Model] = {
    "seasonal_naive_7d": Model(
        name="seasonal_naive_7d",
        version="1",
        description="Same slot, same weekday last week.",
        input_days=_lagged(7),
        predict=lambda target, history: seasonal_naive(target, history, 7),
    ),
    "naive_1d": Model(
        name="naive_1d",
        version="1",
        description="Same slot on the most recent published day.",
        input_days=_lagged(1),
        predict=lambda target, history: seasonal_naive(target, history, 1),
    ),
}
