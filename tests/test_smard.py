import json
import urllib.error
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from dayahead.calendar import local_date, wall_clock
from dayahead.smard import DAY_AHEAD_PRICE_DE_LU, SmardClient, SmardUnavailable, _http_get, parse_points

FIXTURE = Path(__file__).parent / "fixtures" / "smard_4169_DE-LU_quarterhour_1791756000000.json"


def test_parses_a_real_chunk():
    """Captured 2026-10-14: the week of 12 Oct, published up to tomorrow's auction."""
    points = parse_points(json.loads(FIXTURE.read_text()))
    assert len(points) == 7 * 96
    first_ts, first_value = points[0]
    assert local_date(first_ts) == date(2026, 10, 12) and wall_clock(first_ts) == (0, 0)
    assert first_value == 178.73

    published = {local_date(ts) for ts, value in points if value is not None}
    assert max(published) == date(2026, 10, 15)
    assert all(value is None for ts, value in points if local_date(ts) > date(2026, 10, 15))


def test_chunks_covering_picks_overlapping_weeks_only():
    weeks = [1790546400000, 1791151200000, 1791756000000]  # Mondays 28 Sep, 5 Oct, 12 Oct
    fetched = []

    def fetch(url):
        fetched.append(url)
        if url.endswith("index_quarterhour.json"):
            return json.dumps({"timestamps": weeks}).encode()
        return json.dumps({"series": []}).encode()

    chunks = SmardClient(fetch=fetch).chunks_covering(
        DAY_AHEAD_PRICE_DE_LU,
        datetime(2026, 10, 8, tzinfo=UTC),
        datetime(2026, 10, 14, tzinfo=UTC),
    )
    assert sorted(chunks) == weeks[1:]


def test_bad_json_is_retryable_unavailability():
    client = SmardClient(fetch=lambda url: b"<html>maintenance</html>")
    with pytest.raises(SmardUnavailable):
        client.chunk_starts(DAY_AHEAD_PRICE_DE_LU)


def test_network_errors_are_retryable_unavailability(monkeypatch):
    def boom(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SmardUnavailable):
        _http_get("https://www.smard.de/whatever")
