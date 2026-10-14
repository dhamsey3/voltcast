"""The data contract for one delivery day of day-ahead prices.

Two different failure modes, handled differently (see docs/adr/0005):

* **Missing** data (the auction result isn't published yet) means *wait*:
  callers get ``InputsNotReady`` and the orchestrator retries later.
* **Wrong** data (slots that don't fit the calendar, impossible prices)
  means *stop*: ``ContractViolation`` fails the run and pages a human.
"""

from __future__ import annotations

from datetime import date, datetime

from voltcast.calendar import delivery_slots, iso

# SDAC harmonised minimum/maximum clearing prices (EUR/MWh) at the time of
# writing. A value outside this range means the data is wrong, or the limits
# have changed - either way a human should look before we use it.
PRICE_FLOOR = -500.0
PRICE_CAP = 4000.0


class InputsNotReady(Exception):
    """Required data isn't published yet. Retryable."""


class ContractViolation(Exception):
    """Data is present but breaks the contract. Not retryable."""


class TooLate(Exception):
    """The auction for this day has closed; a forecast now would be hindsight. Not retryable."""


def is_complete(day: date, points: list[tuple[datetime, float | None]]) -> bool:
    """True when every expected slot of ``day`` has a value."""
    have = {ts for ts, value in points if value is not None}
    return all(slot in have for slot in delivery_slots(day))


def check_day(day: date, points: list[tuple[datetime, float | None]]) -> None:
    """Raise ``ContractViolation`` listing every problem with a complete day."""
    expected = delivery_slots(day)
    problems: list[str] = []

    stamps = [ts for ts, _ in points]
    if len(stamps) != len(set(stamps)):
        problems.append("duplicate slot timestamps")

    unexpected = sorted(set(stamps) - set(expected))
    if unexpected:
        problems.append(f"{len(unexpected)} slots off the 15-minute grid, first {iso(unexpected[0])}")

    missing = sorted(set(expected) - {ts for ts, value in points if value is not None})
    if missing:
        problems.append(f"{len(missing)} of {len(expected)} slots missing, first {iso(missing[0])}")

    out_of_range = [(ts, v) for ts, v in points if v is not None and not PRICE_FLOOR <= v <= PRICE_CAP]
    if out_of_range:
        ts, v = out_of_range[0]
        problems.append(f"{len(out_of_range)} prices outside [{PRICE_FLOOR}, {PRICE_CAP}], first {v} at {iso(ts)}")

    if problems:
        raise ContractViolation(f"{day}: " + "; ".join(problems))
