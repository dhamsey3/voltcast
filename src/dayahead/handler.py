"""AWS Lambda entry point. Step Functions calls it once per step.

Event: ``{"step": "ingest" | "forecast" | "score" | "check",
"delivery_date": "YYYY-MM-DD", "run_started_at": "<ISO time>"}``.

Without a delivery_date, ``forecast`` targets the auction that was still open
when the run started, and ``score``/``check`` target the day after that. The
anchor is ``run_started_at`` (the Step Functions execution start), so a run
that keeps retrying past 12:00 fails with TooLate instead of quietly
switching to the next day.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta

from dayahead.calendar import berlin_today, next_auction_day, parse_iso
from dayahead.pipeline import Settings, check_published, forecast, ingest, score
from dayahead.smard import SmardClient
from dayahead.store import open_store

logging.getLogger().setLevel(logging.INFO)


def handler(event: dict, context: object = None) -> dict:
    settings = Settings.from_env()
    store = open_store(os.environ["DATA_STORE"])
    now = datetime.now(UTC)
    today = berlin_today(now)
    anchor = parse_iso(event["run_started_at"]) if event.get("run_started_at") else now
    given = date.fromisoformat(event["delivery_date"]) if event.get("delivery_date") else None

    match event["step"]:
        case "ingest":
            start = today - timedelta(days=settings.lookback_days)
            return ingest(store, SmardClient(), start, today + timedelta(days=1), fetched_on=today, settings=settings)
        case "forecast":
            return forecast(store, given or next_auction_day(anchor), settings, now=now)
        case "score":
            return score(store, given or berlin_today(anchor) + timedelta(days=1), settings, now=now)
        case "check":
            return check_published(store, given or berlin_today(anchor) + timedelta(days=1))
        case step:
            raise ValueError(f"unknown step {step!r}")
