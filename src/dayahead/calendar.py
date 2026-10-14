"""Delivery-day arithmetic for the German day-ahead market.

The auction trades 15-minute products for each *local* (Europe/Berlin) day.
A normal day has 96 slots, the spring-forward day 92 and the fall-back day
100. Everything below works in UTC internally and converts at the edges.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
SLOT = timedelta(minutes=15)


def delivery_slots(day: date) -> list[datetime]:
    """UTC start time of every 15-minute slot in a Berlin delivery day."""
    start = datetime.combine(day, time(0), BERLIN).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(0), BERLIN).astimezone(UTC)
    slots = []
    t = start
    while t < end:
        slots.append(t)
        t += SLOT
    return slots


def gate_closure(day: date) -> datetime:
    """Bids for ``day`` must be in by 12:00 Berlin the day before."""
    return datetime.combine(day - timedelta(days=1), time(12), BERLIN)


def next_auction_day(now: datetime) -> date:
    """The delivery day whose auction hasn't closed yet."""
    tomorrow = berlin_today(now) + timedelta(days=1)
    return tomorrow if now < gate_closure(tomorrow) else tomorrow + timedelta(days=1)


def local_date(ts: datetime) -> date:
    return ts.astimezone(BERLIN).date()


def wall_clock(ts: datetime) -> tuple[int, int]:
    """(hour, minute) on the Berlin clock - the key naive models align on."""
    local = ts.astimezone(BERLIN)
    return local.hour, local.minute


def berlin_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(BERLIN).date()


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


def to_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
