from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from conftest import FakeSmard, default_price
from voltcast.calendar import next_auction_day
from voltcast.contract import ContractViolation, InputsNotReady, TooLate
from voltcast.pipeline import backfill, check_published, forecast, ingest, report, score
from voltcast.store import keys

TODAY = date(2026, 10, 14)
TOMORROW = TODAY + timedelta(days=1)
NOW = datetime(2026, 10, 14, 7, 0, tzinfo=UTC)  # 09:00 Berlin, before the auction


def run_ingest(store, settings, smard, start=TODAY - timedelta(days=14), end=TOMORROW):
    return ingest(store, smard.client(), start, end, fetched_on=TODAY, settings=settings)


def test_ingest_curates_published_days_and_waits_for_the_rest(store, settings):
    smard = FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY)
    result = run_ingest(store, settings, smard)
    assert result["pending"] == [TOMORROW.isoformat()]
    assert len(result["curated"]) == 15
    doc = store.get_json(keys.actuals("DE-LU", TODAY.isoformat()))
    assert len(doc["slots"]) == 96
    assert doc["raw_snapshot"].startswith("raw/smard/4169_DE-LU_quarterhour/fetched=2026-10-14/")


def test_ingest_is_idempotent(store, settings):
    smard = FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY)
    run_ingest(store, settings, smard)
    again = run_ingest(store, settings, smard)
    assert again["curated"] == [] and again["revised"] == []


def test_ingest_reports_source_revisions(store, settings):
    run_ingest(store, settings, FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY))
    revised_source = FakeSmard(
        TODAY - timedelta(days=14),
        TOMORROW,
        published_until=TODAY,
        price=lambda ts: default_price(ts) + (1 if ts.date() == date(2026, 10, 10) else 0),
    )
    result = run_ingest(store, settings, revised_source)
    assert "2026-10-10" in result["revised"]


def test_wrong_data_stops_the_pipeline(store, settings):
    broken = FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY, price=lambda ts: 99999.0)
    with pytest.raises(ContractViolation):
        run_ingest(store, settings, broken)


def test_forecast_publishes_champion_with_lineage(store, settings):
    run_ingest(store, settings, FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY))
    result = forecast(store, TOMORROW, settings, now=NOW)
    assert result["models"] == {"naive_1d": "ok", "seasonal_naive_7d": "ok"}

    published = store.get_json(keys.published(TOMORROW.isoformat()))
    assert published["model"] == "naive_1d" and published["role"] == "champion"
    assert published["inputs"][0]["key"] == keys.actuals("DE-LU", "2026-10-14")
    assert len(published["inputs"][0]["sha256"]) == 64
    assert published["code_version"] == "test"
    assert store.get_json(keys.LATEST) == published


def test_published_forecast_is_never_rewritten(store, settings):
    run_ingest(store, settings, FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY))
    forecast(store, TOMORROW, settings, now=NOW)
    first = store.get_json(keys.published(TOMORROW.isoformat()))
    assert forecast(store, TOMORROW, settings, now=NOW + timedelta(hours=1))["status"] == "already_published"
    assert store.get_json(keys.published(TOMORROW.isoformat())) == first


def test_missing_champion_input_means_wait(store, settings):
    with pytest.raises(InputsNotReady):
        forecast(store, TOMORROW, settings, now=NOW)
    assert store.get_json(keys.published(TOMORROW.isoformat())) is None


def test_failing_challenger_does_not_block_champion(store, settings):
    # Only the last three days curated: champion (t-1) can run, seasonal_naive_7d (t-7) can't.
    smard = FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY)
    run_ingest(store, settings, smard, start=TODAY - timedelta(days=2))
    result = forecast(store, TOMORROW, settings, now=NOW)
    assert result["models"]["naive_1d"] == "ok"
    assert result["models"]["seasonal_naive_7d"].startswith("skipped")
    assert store.get_json(keys.published(TOMORROW.isoformat())) is not None


def test_live_forecast_after_gate_closure_is_refused(store, settings):
    run_ingest(store, settings, FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TOMORROW))
    after_auction = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)  # 12:00 Berlin
    with pytest.raises(TooLate):
        forecast(store, TOMORROW, settings, now=after_auction)
    assert store.list_keys("forecasts/") == []


def test_next_auction_day_rolls_over_at_noon_berlin():
    assert next_auction_day(datetime(2026, 10, 14, 9, 59, tzinfo=UTC)) == date(2026, 10, 15)
    assert next_auction_day(datetime(2026, 10, 14, 10, 0, tzinfo=UTC)) == date(2026, 10, 16)


def test_score_measures_error_against_cleared_prices(store, settings):
    smard = FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY)
    run_ingest(store, settings, smard)
    forecast(store, TOMORROW, settings, now=NOW)

    with pytest.raises(InputsNotReady):
        score(store, TOMORROW, settings, now=NOW)

    # The auction clears; tomorrow's prices are published.
    smard.published_until = TOMORROW
    run_ingest(store, settings, smard)
    result = score(store, TOMORROW, settings, now=NOW)

    # default_price moves 0.5 EUR/MWh per day of month: a 7-day lag is 3.5 off, 1-day lag 0.5.
    assert result["mae"] == {"seasonal_naive_7d": 3.5, "naive_1d": 0.5}
    assert store.get_json(keys.score(TOMORROW.isoformat(), "naive_1d"))["bias"] == -0.5


def test_check_reports_missed_deadline(store, settings):
    assert check_published(store, TOMORROW)["published"] is False


def test_backfill_replays_without_publishing(store, settings):
    smard = FakeSmard(date(2026, 9, 20), TODAY, published_until=TODAY)
    scored = backfill(store, smard.client(), date(2026, 10, 1), date(2026, 10, 10), settings)
    assert len(scored) == 10 and all(isinstance(v, dict) for v in scored.values())
    assert store.list_keys("published/") == []
    assert store.get_json(keys.forecast("2026-10-05", "naive_1d"))["mode"] == "backfill"

    table = report(store, date(2026, 10, 1), date(2026, 10, 10))
    assert table["seasonal_naive_7d"]["days"] == 10
    assert table["seasonal_naive_7d"]["live_days"] == 0


def test_challengers_are_configurable(store, settings):
    run_ingest(store, settings, FakeSmard(TODAY - timedelta(days=14), TOMORROW, published_until=TODAY))
    result = forecast(store, TOMORROW, replace(settings, challengers=()), now=NOW)
    assert list(result["models"]) == ["naive_1d"]
