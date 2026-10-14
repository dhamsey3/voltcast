"""Command line for local runs, backfills and reports.

    python -m dayahead ingest
    python -m dayahead forecast --date 2026-10-16
    python -m dayahead backfill --start 2026-09-01 --end 2026-10-14
    python -m dayahead report --days 30

``--store`` takes a local folder (default ./data) or s3://bucket.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta

from dayahead.calendar import berlin_today, next_auction_day
from dayahead.pipeline import Settings, backfill, check_published, forecast, ingest, report, score
from dayahead.smard import SmardClient
from dayahead.store import open_store


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dayahead")
    parser.add_argument("--store", default=os.environ.get("DATA_STORE", "data"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="fetch recent prices and curate complete days")
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    for name, help_text in [
        ("forecast", "forecast a delivery day (default: next auction still open)"),
        ("score", "score forecasts for a delivery day (default: tomorrow)"),
        ("check", "check a delivery day's forecast was published (default: tomorrow)"),
    ]:
        sub.add_parser(name, help=help_text).add_argument("--date", type=date.fromisoformat)
    p = sub.add_parser("backfill", help="replay the service over past days")
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p = sub.add_parser("report", help="mean error per model")
    p.add_argument("--days", type=int, default=30)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    store = open_store(args.store)
    settings = Settings.from_env()
    now = datetime.now(UTC)
    today = berlin_today(now)
    given = getattr(args, "date", None)
    target = given or today + timedelta(days=1)

    match args.command:
        case "ingest":
            start = args.start or today - timedelta(days=settings.lookback_days)
            end = args.end or today + timedelta(days=1)
            result = ingest(store, SmardClient(), start, end, fetched_on=today, settings=settings)
        case "forecast":
            result = forecast(store, given or next_auction_day(now), settings, now=now)
        case "score":
            result = score(store, target, settings, now=now)
        case "check":
            result = check_published(store, target)
        case "backfill":
            result = backfill(store, SmardClient(), args.start, args.end, settings)
        case "report":
            result = report(store, today - timedelta(days=args.days), today + timedelta(days=1))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
