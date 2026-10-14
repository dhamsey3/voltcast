import json
from datetime import UTC, date, datetime, timedelta

import pytest

from conftest import FakeSmard
from dayahead import handler as lambda_handler
from dayahead.contract import TooLate
from dayahead.store import LocalStore, keys

TODAY = date(2026, 10, 14)


@pytest.fixture
def lambda_env(tmp_path, monkeypatch):
    smard = FakeSmard(TODAY - timedelta(days=21), TODAY + timedelta(days=1), published_until=TODAY)
    monkeypatch.setenv("DATA_STORE", str(tmp_path))
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "dayahead-pipeline")
    monkeypatch.setattr(lambda_handler, "SmardClient", smard.client)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 14, 7, 0, tzinfo=UTC)  # 09:00 Berlin

    monkeypatch.setattr(lambda_handler, "datetime", Frozen)
    return LocalStore(tmp_path)


def test_daily_forecast_run(lambda_env, capsys):
    lambda_handler.handler({"step": "ingest"})
    result = lambda_handler.handler({"step": "forecast"})
    assert result["delivery_date"] == "2026-10-15"
    assert lambda_env.get_json(keys.published("2026-10-15"))["model"] == "naive_1d"

    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert {k: v for k, v in emitted[-1].items() if k == "ForecastPublished"} == {"ForecastPublished": 1}
    assert emitted[-1]["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "DayAhead"


def test_deadline_check_emits_missing_metric(lambda_env, capsys):
    assert lambda_handler.handler({"step": "check"})["published"] is False
    assert '"ForecastMissing": 1' in capsys.readouterr().out


def test_retry_past_gate_closure_fails_instead_of_switching_day(lambda_env, monkeypatch):
    lambda_handler.handler({"step": "ingest"})

    class AfterNoon(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 14, 10, 30, tzinfo=UTC)  # 12:30 Berlin

    monkeypatch.setattr(lambda_handler, "datetime", AfterNoon)
    with pytest.raises(TooLate):
        lambda_handler.handler({"step": "forecast", "run_started_at": "2026-10-14T07:00:00.123Z"})
    assert lambda_env.list_keys("forecasts/2026-10-16/") == []


def test_unknown_step_is_an_error(lambda_env):
    with pytest.raises(ValueError, match="unknown step"):
        lambda_handler.handler({"step": "train"})
