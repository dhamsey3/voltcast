"""A fake SMARD that serves synthetic weekly chunks, so pipeline tests run offline."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

import pytest

from voltcast.calendar import BERLIN, delivery_slots, to_ms
from voltcast.pipeline import Settings
from voltcast.smard import BASE_URL, DAY_AHEAD_PRICE_DE_LU, SmardClient
from voltcast.store import LocalStore

SERIES = DAY_AHEAD_PRICE_DE_LU


def default_price(ts: datetime) -> float:
    """Deterministic, varies by hour and day, never out of contract."""
    return round(50 + ts.hour * 2 + ts.day * 0.5, 2)


class FakeSmard:
    """Serves SMARD URLs for ``first``..``last`` with prices up to ``published_until``."""

    def __init__(
        self,
        first: date,
        last: date,
        published_until: date,
        price: Callable[[datetime], float] = default_price,
    ):
        self.price = price
        self.published_until = published_until
        monday = first - timedelta(days=first.weekday())
        self.weeks = []
        while monday <= last:
            self.weeks.append(monday)
            monday += timedelta(days=7)
        self.requests: list[str] = []

    def chunk_ms(self, monday: date) -> int:
        return to_ms(datetime.combine(monday, time(0), BERLIN))

    def fetch(self, url: str) -> bytes:
        self.requests.append(url)
        prefix = f"{BASE_URL}/{SERIES.filter_id}/{SERIES.region}/"
        name = url.removeprefix(prefix)
        if name == f"index_{SERIES.resolution}.json":
            return json.dumps({"timestamps": [self.chunk_ms(m) for m in self.weeks]}).encode()
        for monday in self.weeks:
            if name == f"{SERIES.slug}_{self.chunk_ms(monday)}.json":
                series = []
                for offset in range(7):
                    day = monday + timedelta(days=offset)
                    for slot in delivery_slots(day):
                        value = self.price(slot) if day <= self.published_until else None
                        series.append([to_ms(slot), value])
                return json.dumps({"meta_data": {"version": 1}, "series": series}).encode()
        raise AssertionError(f"unexpected URL {url}")

    def client(self) -> SmardClient:
        return SmardClient(fetch=self.fetch)


@pytest.fixture
def store(tmp_path) -> LocalStore:
    return LocalStore(tmp_path / "data")


@pytest.fixture
def settings() -> Settings:
    return Settings(code_version="test")
