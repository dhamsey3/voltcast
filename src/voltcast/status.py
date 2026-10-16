"""The public status page's data: what was promised, what happened, what it cost.

``collect`` reads the store (and the AWS Budget, when given) into one plain
dict. It is published as status.json and rendered by ``voltcast.page``, so the
page can be rebuilt from any copy of the data. Only live forecasts count here;
the backfill replay stays in ``voltcast report``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from voltcast.calendar import BERLIN, berlin_today, iso
from voltcast.pipeline import SOURCE, UNIT
from voltcast.store import Store, keys

REGION = "DE-LU"
# The deadline check runs at 10:15 Berlin (check_schedule in infrastructure/variables.tf).
DEADLINE = time(10, 15)
WINDOWS = {"last_7_days": 7, "last_30_days": 30, "all_live_days": None}
TREND_DAYS = 30


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 2)


def _live_scores(store: Store) -> dict[str, dict[str, dict]]:
    """{delivery day: {model: score}} for every live forecast that has been scored."""
    scores: dict[str, dict[str, dict]] = defaultdict(dict)
    for key in store.list_keys("scores/"):
        result = store.get_json(key)
        if result and result["mode"] == "live":
            scores[result["delivery_date"]][result["model"]] = result
    return dict(sorted(scores.items()))


def _scored_day(store: Store, day: str, scores: dict[str, dict]) -> dict:
    actual = store.get_json(keys.actuals(REGION, day))
    published = store.get_json(keys.published(day))
    forecast = {s["start"]: s["price"] for s in published["slots"]} if published else {}
    return {
        "delivery_date": day,
        "model": published["model"] if published else None,
        "slots": [
            {"start": s["start"], "actual": s["price"], "forecast": forecast.get(s["start"])} for s in actual["slots"]
        ],
        "scores": {model: {k: s[k] for k in ("mae", "rmse", "bias", "role")} for model, s in sorted(scores.items())},
    }


def _forecast_view(doc: dict, *, with_slots: bool = True) -> dict:
    view = {k: doc[k] for k in ("delivery_date", "model", "model_version", "code_version", "as_of", "inputs")}
    return view | {"slots": doc["slots"]} if with_slots else view


def _promise(store: Store, now: datetime) -> dict:
    """Is the next delivery day's forecast out, still due today, or late?"""
    day = berlin_today(now) + timedelta(days=1)
    deadline = datetime.combine(day - timedelta(days=1), DEADLINE, BERLIN)
    published = store.get_json(keys.published(day.isoformat()))
    if published:
        state = "published"
    elif now < deadline:
        state = "due"
    else:
        state = "missing"
    return {
        "delivery_date": day.isoformat(),
        "deadline": iso(deadline),
        "state": state,
        "published_at": published["as_of"] if published else None,
    }


def _rolling(scores: dict[str, dict[str, dict]], today: date) -> dict[str, dict[str, dict]]:
    """Mean daily error per model over each window, live days only."""
    out = {}
    for name, days in WINDOWS.items():
        start = today - timedelta(days=days) if days else date.min
        rows: dict[str, list[dict]] = defaultdict(list)
        for day, by_model in scores.items():
            if date.fromisoformat(day) > start:
                for model, result in by_model.items():
                    rows[model].append(result)
        out[name] = {
            model: {
                "days": len(results),
                "mae": _mean([r["mae"] for r in results]),
                "rmse": _mean([r["rmse"] for r in results]),
                "bias": _mean([r["bias"] for r in results]),
            }
            for model, results in sorted(rows.items())
        }
    return out


def collect(store: Store, now: datetime, budget: dict | None = None) -> dict[str, Any]:
    today = berlin_today(now)
    scores = _live_scores(store)
    last_scored = next(reversed(scores), None)

    latest = store.get_json(keys.LATEST)
    upcoming = latest if latest and (last_scored is None or latest["delivery_date"] > last_scored) else None
    newest = upcoming or (store.get_json(keys.published(last_scored)) if last_scored else latest)

    return {
        "generated_at": iso(now),
        "region": REGION,
        "unit": UNIT,
        "source": SOURCE,
        "champion": newest["model"] if newest else None,
        "live_since": next(iter(scores), None),
        "promise": _promise(store, now),
        "scored": _scored_day(store, last_scored, scores[last_scored]) if last_scored else None,
        "upcoming": _forecast_view(upcoming) if upcoming else None,
        "model": _forecast_view(newest, with_slots=False) if newest else None,
        "rolling": _rolling(scores, today),
        "trend": [
            {"delivery_date": day, "mae": {model: s["mae"] for model, s in by_model.items()}}
            for day, by_model in list(scores.items())[-TREND_DAYS:]
        ],
        "cost": budget,
    }


def read_budget(client: Any, account_id: str, name: str, now: datetime) -> dict | None:
    """Month-to-date spend, the month's forecast and past months from an AWS Budget.

    The Budgets API itself is free, unlike Cost Explorer's per-request charge.
    Returns None when the budget doesn't exist (yet).
    """
    try:
        budget = client.describe_budget(AccountId=account_id, BudgetName=name)["Budget"]
    except client.exceptions.NotFoundException:
        return None
    spend = budget.get("CalculatedSpend", {})
    forecast = spend.get("ForecastedSpend")

    first = budget["TimePeriod"]["Start"].astimezone(UTC).date().replace(day=1)
    history = client.describe_budget_performance_history(
        AccountId=account_id,
        BudgetName=name,
        TimePeriod={"Start": datetime.combine(first, time(0), UTC), "End": now},
    )["BudgetPerformanceHistory"]
    months = [
        {"month": period["TimePeriod"]["Start"].astimezone(UTC).strftime("%Y-%m"), "actual": float(amount["Amount"])}
        for period in history.get("BudgetedAndActualAmountsList", [])
        if (amount := period.get("ActualAmount"))
    ]
    return {
        "budget": name,
        "limit": float(budget["BudgetLimit"]["Amount"]),
        "unit": budget["BudgetLimit"]["Unit"],
        "month": now.astimezone(UTC).strftime("%Y-%m"),
        "month_to_date": float(spend.get("ActualSpend", {}).get("Amount", 0)),
        "forecast": float(forecast["Amount"]) if forecast else None,
        "months": sorted(months, key=lambda m: m["month"]),
    }
