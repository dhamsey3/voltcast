import json
import re
from datetime import UTC, date, datetime, time, timedelta

import pytest

from conftest import FakeSmard
from voltcast.calendar import BERLIN
from voltcast.page import _nice_ticks, render, write_site
from voltcast.pipeline import backfill, forecast, ingest, score
from voltcast.status import collect, read_budget

TODAY = date(2026, 10, 14)
LIVE_DAYS = [date(2026, 10, 12), date(2026, 10, 13), TODAY]


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), BERLIN).astimezone(UTC)


@pytest.fixture
def live_store(store, settings):
    """Three live days forecast and scored, and tomorrow's forecast published."""
    smard = FakeSmard(TODAY - timedelta(days=21), TODAY + timedelta(days=1), published_until=TODAY)
    ingest(store, smard.client(), TODAY - timedelta(days=21), TODAY, fetched_on=TODAY, settings=settings)
    for day in [*LIVE_DAYS, TODAY + timedelta(days=1)]:
        forecast(store, day, settings, now=at(day - timedelta(days=1), 9))
    for day in LIVE_DAYS:
        score(store, day, settings, now=at(day, 14, 30))
    return store


def test_collect_shows_the_latest_scored_day_and_the_next_forecast(live_store):
    status = collect(live_store, at(TODAY, 15))
    assert status["scored"]["delivery_date"] == "2026-10-14"
    assert status["scored"]["model"] == "naive_1d"
    assert len(status["scored"]["slots"]) == 96
    assert set(status["scored"]["scores"]) == {"naive_1d", "seasonal_naive_7d"}
    assert status["upcoming"]["delivery_date"] == "2026-10-15"
    assert status["model"]["code_version"] == "test" and "slots" not in status["model"]
    assert status["live_since"] == "2026-10-12"
    assert [t["delivery_date"] for t in status["trend"]] == ["2026-10-12", "2026-10-13", "2026-10-14"]


def test_rolling_error_averages_live_days_per_window(live_store):
    status = collect(live_store, at(TODAY, 15))
    week = status["rolling"]["last_7_days"]["naive_1d"]
    daily = [t["mae"]["naive_1d"] for t in status["trend"]]
    assert week["days"] == 3
    assert week["mae"] == round(sum(daily) / 3, 2)
    assert status["rolling"]["all_live_days"]["seasonal_naive_7d"]["days"] == 3


@pytest.mark.parametrize(
    ("now", "state"),
    [(at(TODAY, 8), "due"), (at(TODAY, 10, 16), "missing"), (at(TODAY - timedelta(days=1), 10), "published")],
)
def test_promise_tracks_the_deadline(store, settings, now, state):
    smard = FakeSmard(TODAY - timedelta(days=14), TODAY, published_until=TODAY - timedelta(days=1))
    ingest(store, smard.client(), TODAY - timedelta(days=14), TODAY, fetched_on=TODAY, settings=settings)
    forecast(store, TODAY, settings, now=at(TODAY - timedelta(days=1), 9))
    promise = collect(store, now)["promise"]
    assert promise["state"] == state
    assert promise["delivery_date"] == (now.astimezone(BERLIN).date() + timedelta(days=1)).isoformat()


def test_replayed_days_stay_off_the_page(store, settings):
    smard = FakeSmard(date(2026, 9, 20), TODAY, published_until=TODAY)
    backfill(store, smard.client(), date(2026, 10, 1), date(2026, 10, 10), settings)
    status = collect(store, at(TODAY, 15))
    assert status["scored"] is None
    assert status["trend"] == []
    assert status["rolling"]["all_live_days"] == {}


def test_page_renders_charts_tables_and_escapes_text(live_store):
    status = collect(live_store, at(TODAY, 15))
    status["model"]["inputs"][0]["key"] = "<script>alert(1)</script>"
    page = render(status)
    assert page.count('<figure class="chart"') == 3  # last scored day, next forecast, daily error
    assert "Cleared price" in page and "Forecast (naive_1d)" in page
    # Narrow charts hide the 06:00 and 18:00 ticks (CSS), keeping 00:00, 12:00 and 24:00.
    assert re.findall(r'<span class="xlab minor"[^>]*>([^<]+)<', page)[:2] == ["06:00", "18:00"]
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    # One table row per quarter-hour behind the price charts, so values never depend on hover.
    assert len(re.findall(r"<tr><th>\d\d:\d\d</th>", page)) == 2 * 96
    for blob in re.findall(r'<script type="application/json" class="chart-data">(.*?)</script>', page, re.S):
        assert len(json.loads(blob)["x"]) in (3, 96)
    assert not re.search(r'(src|href)="https?://(?!github\.com/dhamsey3/voltcast)', page)


def test_page_renders_before_any_live_data(store):
    page = render(collect(store, at(TODAY, 8)))
    assert "No live day has been scored yet." in page
    assert '<figure class="chart"' not in page


def test_write_site_writes_the_page_and_its_data(live_store, tmp_path):
    status = collect(live_store, at(TODAY, 15))
    files = write_site(status, tmp_path / "site")
    assert sorted(f.name for f in files) == ["index.html", "status.json"]
    assert json.loads((tmp_path / "site" / "status.json").read_text()) == status


class FakeBudgets:
    class exceptions:
        class NotFoundException(Exception):
            pass

    def __init__(self, exists=True):
        self.exists = exists

    def describe_budget(self, AccountId, BudgetName):
        if not self.exists:
            raise self.exceptions.NotFoundException()
        return {
            "Budget": {
                "BudgetLimit": {"Amount": "5.0", "Unit": "USD"},
                "TimePeriod": {"Start": datetime(2026, 10, 1, tzinfo=UTC)},
                "CalculatedSpend": {"ActualSpend": {"Amount": "0.42"}, "ForecastedSpend": {"Amount": "1.17"}},
            }
        }

    def describe_budget_performance_history(self, AccountId, BudgetName, TimePeriod):
        assert TimePeriod["Start"] == datetime(2026, 10, 1, tzinfo=UTC)
        return {
            "BudgetPerformanceHistory": {
                "BudgetedAndActualAmountsList": [
                    {"TimePeriod": {"Start": datetime(2026, 10, 1, tzinfo=UTC)}, "ActualAmount": {"Amount": "0.42"}}
                ]
            }
        }


def test_read_budget_reports_spend_forecast_and_months():
    cost = read_budget(FakeBudgets(), "123456789012", "voltcast-monthly", at(TODAY, 15))
    assert cost == {
        "budget": "voltcast-monthly",
        "limit": 5.0,
        "unit": "USD",
        "month": "2026-10",
        "month_to_date": 0.42,
        "forecast": 1.17,
        "months": [{"month": "2026-10", "actual": 0.42}],
    }
    page = render(collect_with_cost(cost))
    assert "$0.42" in page and "of a $5.00 monthly budget" in page and "October 2026 (so far)" in page


def test_missing_budget_means_no_cost_section():
    assert read_budget(FakeBudgets(exists=False), "123456789012", "voltcast-monthly", at(TODAY, 15)) is None


def collect_with_cost(cost):
    from voltcast.store import LocalStore

    status = collect(LocalStore("/nonexistent"), at(TODAY, 15), cost)
    assert status["cost"] is cost
    return status


@pytest.mark.parametrize(
    ("lo", "hi", "expected"),
    [
        (89.4, 270.1, [50, 100, 150, 200, 250, 300]),
        (-12.0, 30.0, [-20, -10, 0, 10, 20, 30]),
        (5, 5, [4, 4.5, 5, 5.5, 6]),
    ],
)
def test_axis_ticks_are_round_numbers(lo, hi, expected):
    assert _nice_ticks(lo, hi) == expected


def test_track_record_shows_each_distinct_window_once(live_store):
    page = render(collect(live_store, at(TODAY, 15)))
    # Three live days: the 7-day, 30-day and all-time windows hold the same days.
    assert "Since going live" in page
    assert "Last 7 days" not in page and "Last 30 days" not in page
