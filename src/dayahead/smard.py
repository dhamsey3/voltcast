"""Client for SMARD, the Bundesnetzagentur's open electricity-market data.

SMARD serves each series as weekly JSON chunks (Monday 00:00 Berlin) plus an
index listing the chunk start times. No API key; data is CC BY 4.0
(attribution: Bundesnetzagentur | SMARD.de).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from dayahead.calendar import from_ms, to_ms

BASE_URL = "https://www.smard.de/app/chart_data"
USER_AGENT = "dayahead-forecaster/0.1 (+https://github.com/dhamsey3/aws-mlops-predictive-maintenance)"


class SmardUnavailable(Exception):
    """SMARD could not be reached or returned something unusable. Retryable."""


@dataclass(frozen=True)
class Series:
    filter_id: int
    region: str
    resolution: str = "quarterhour"

    @property
    def slug(self) -> str:
        return f"{self.filter_id}_{self.region}_{self.resolution}"


# Day-ahead auction clearing price, Germany/Luxembourg bidding zone, EUR/MWh.
# Before 2025-10-01 the auction was hourly and SMARD repeats each hourly price
# across its four quarter-hours.
DAY_AHEAD_PRICE_DE_LU = Series(filter_id=4169, region="DE-LU")

Fetch = Callable[[str], bytes]


def _http_get(url: str, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SmardUnavailable(f"GET {url} failed: {exc}") from exc


class SmardClient:
    def __init__(self, fetch: Fetch = _http_get, base_url: str = BASE_URL):
        self._fetch = fetch
        self._base_url = base_url

    def _get_json(self, url: str) -> dict:
        try:
            return json.loads(self._fetch(url))
        except json.JSONDecodeError as exc:
            raise SmardUnavailable(f"GET {url} returned invalid JSON") from exc

    def chunk_starts(self, series: Series) -> list[int]:
        url = f"{self._base_url}/{series.filter_id}/{series.region}/index_{series.resolution}.json"
        return sorted(self._get_json(url)["timestamps"])

    def chunk(self, series: Series, start_ms: int) -> dict:
        url = f"{self._base_url}/{series.filter_id}/{series.region}/{series.slug}_{start_ms}.json"
        return self._get_json(url)

    def chunks_covering(self, series: Series, start: datetime, end: datetime) -> dict[int, dict]:
        """Raw chunks whose week overlaps [start, end). Keyed by chunk start (ms)."""
        # A chunk spans one week; allow a day of slack for DST-shifted weeks.
        span_ms = to_ms(start + timedelta(days=8)) - to_ms(start)
        wanted = [ts for ts in self.chunk_starts(series) if ts < to_ms(end) and ts + span_ms > to_ms(start)]
        return {ts: self.chunk(series, ts) for ts in wanted}


def parse_points(raw_chunk: dict) -> list[tuple[datetime, float | None]]:
    """SMARD's [[epoch_ms, value|null], ...] as (UTC datetime, value)."""
    return [(from_ms(ms), None if value is None else float(value)) for ms, value in raw_chunk["series"]]
