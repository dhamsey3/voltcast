"""The daily steps: ingest, forecast, score, check.

Every step is idempotent - safe to retry, re-run or backfill - because it
reads and writes deterministic keys and never rewrites a published forecast.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from voltcast import metrics
from voltcast.calendar import BERLIN, berlin_today, delivery_slots, gate_closure, iso, local_date, parse_iso
from voltcast.contract import InputsNotReady, TooLate, check_day, is_complete
from voltcast.models import MODELS, Model
from voltcast.smard import DAY_AHEAD_PRICE_DE_LU, Series, SmardClient, parse_points
from voltcast.store import Store, keys

log = logging.getLogger(__name__)

SOURCE = "Bundesnetzagentur | SMARD.de (CC BY 4.0)"
UNIT = "EUR/MWh"


@dataclass(frozen=True)
class Settings:
    region: str = "DE-LU"
    # Chosen on the 2025-10 to 2026-10 backfill - see docs/adr/0003.
    champion: str = "naive_1d"
    challengers: tuple[str, ...] = ("seasonal_naive_7d",)
    lookback_days: int = 14
    code_version: str = "dev"

    @classmethod
    def from_env(cls) -> Settings:
        challengers = os.environ.get("CHALLENGERS", ",".join(cls.challengers))
        return cls(
            champion=os.environ.get("CHAMPION", cls.champion),
            challengers=tuple(name for name in challengers.split(",") if name),
            code_version=os.environ.get("CODE_VERSION", cls.code_version),
        )


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _sha256(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


# --- ingest -----------------------------------------------------------------


def ingest(
    store: Store,
    client: SmardClient,
    start: date,
    end: date,
    *,
    fetched_on: date,
    settings: Settings,
    series: Series = DAY_AHEAD_PRICE_DE_LU,
) -> dict:
    """Snapshot SMARD chunks covering ``start..end`` and curate complete days.

    Days whose auction result isn't out yet are reported as pending, not
    errors. A complete day that breaks the contract raises ContractViolation.
    """
    window_start = delivery_slots(start)[0]
    window_end = delivery_slots(end + timedelta(days=1))[0]

    by_day: dict[date, list] = defaultdict(list)
    raw_key_for_day: dict[date, str] = {}
    for chunk_ms, raw in client.chunks_covering(series, window_start, window_end).items():
        raw_key = keys.raw(series.slug, fetched_on.isoformat(), chunk_ms)
        store.put_json(raw_key, raw)
        for ts, value in parse_points(raw):
            day = local_date(ts)
            if start <= day <= end:
                by_day[day].append((ts, value))
                raw_key_for_day[day] = raw_key

    curated, pending, revised = [], [], []
    for day in _days(start, end):
        points = by_day.get(day, [])
        if not is_complete(day, points):
            pending.append(day.isoformat())
            continue
        check_day(day, points)

        slots = [{"start": iso(ts), "price": value} for ts, value in sorted(points)]
        key = keys.actuals(settings.region, day.isoformat())
        existing = store.get_json(key)
        if existing is not None and existing["slots"] == slots:
            continue
        if existing is not None:
            log.warning("source revised published prices for %s", day)
            revised.append(day.isoformat())
        store.put_json(
            key,
            {
                "delivery_date": day.isoformat(),
                "region": settings.region,
                "unit": UNIT,
                "source": SOURCE,
                "raw_snapshot": raw_key_for_day[day],
                "slots": slots,
            },
        )
        curated.append(day.isoformat())

    metrics.emit({"DaysCurated": len(curated), "DaysRevised": len(revised)})
    return {"curated": curated, "pending": pending, "revised": revised}


# --- forecast ---------------------------------------------------------------


def _load_inputs(store: Store, model: Model, target: date, region: str) -> tuple[dict, list]:
    history, lineage = {}, []
    for day in model.input_days(target):
        if day >= target:
            raise ValueError(f"{model.name} asked for {day}, which is not before {target}")
        key = keys.actuals(region, day.isoformat())
        doc = store.get_json(key)
        if doc is None:
            raise InputsNotReady(f"{model.name} needs actual prices for {day}")
        history[day] = [(parse_iso(s["start"]), s["price"]) for s in doc["slots"]]
        lineage.append({"key": key, "sha256": _sha256(doc["slots"])})
    return history, lineage


def _forecast_doc(store, model, target, settings, *, role, mode, as_of) -> dict:
    history, lineage = _load_inputs(store, model, target, settings.region)
    prices = model.predict(target, history)
    return {
        "delivery_date": target.isoformat(),
        "region": settings.region,
        "unit": UNIT,
        "model": model.name,
        "model_version": model.version,
        "role": role,
        "mode": mode,
        "as_of": iso(as_of),
        "code_version": settings.code_version,
        "inputs": lineage,
        "slots": [{"start": iso(ts), "price": round(value, 2)} for ts, value in prices],
    }


def forecast(store: Store, target: date, settings: Settings, *, now: datetime, mode: str = "live") -> dict:
    """Forecast ``target`` with the champion and every challenger.

    Live mode publishes the champion. A failing challenger is logged and
    skipped; a champion that can't run fails the step.
    """
    day = target.isoformat()
    if mode == "live" and store.get_json(keys.published(day)) is not None:
        return {"delivery_date": day, "status": "already_published"}
    if mode == "live" and now >= gate_closure(target):
        raise TooLate(f"auction for {day} closed at {iso(gate_closure(target))}; use backfill for past days")

    results = {}
    for name in (settings.champion, *settings.challengers):
        role = "champion" if name == settings.champion else "challenger"
        if store.get_json(keys.forecast(day, name)) is not None:
            results[name] = "exists"
            continue
        try:
            doc = _forecast_doc(store, MODELS[name], target, settings, role=role, mode=mode, as_of=now)
        except Exception as exc:
            if role == "champion":
                raise
            log.warning("challenger %s skipped for %s: %s", name, day, exc)
            metrics.emit({"ChallengerFailed": 1}, {"Model": name})
            results[name] = f"skipped: {exc}"
            continue
        store.put_json(keys.forecast(day, name), doc)
        results[name] = "ok"

    if mode == "live":
        champion_doc = store.get_json(keys.forecast(day, settings.champion))
        store.put_json(keys.published(day), champion_doc)
        latest = store.get_json(keys.LATEST)
        if latest is None or latest["delivery_date"] <= day:
            store.put_json(keys.LATEST, champion_doc)
        metrics.emit({"ForecastPublished": 1})

    return {"delivery_date": day, "status": "ok", "models": results}


# --- score ------------------------------------------------------------------


def score(store: Store, target: date, settings: Settings, *, now: datetime) -> dict:
    """Score every forecast for ``target`` against the cleared prices."""
    day = target.isoformat()
    actual_doc = store.get_json(keys.actuals(settings.region, day))
    if actual_doc is None:
        raise InputsNotReady(f"actual prices for {day} not published yet")
    actual = {s["start"]: s["price"] for s in actual_doc["slots"]}

    results = {}
    for key in store.list_keys(f"forecasts/{day}/"):
        fc = store.get_json(key)
        errors = [slot["price"] - actual[slot["start"]] for slot in fc["slots"]]
        result = {
            "delivery_date": day,
            "model": fc["model"],
            "model_version": fc["model_version"],
            "role": fc["role"],
            "mode": fc["mode"],
            "n_slots": len(errors),
            "mae": round(sum(abs(e) for e in errors) / len(errors), 3),
            "rmse": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 3),
            "bias": round(sum(errors) / len(errors), 3),
            "scored_at": iso(now),
        }
        store.put_json(keys.score(day, fc["model"]), result)
        metrics.emit({"MAE": result["mae"], "Bias": result["bias"]}, {"Model": fc["model"]})
        results[fc["model"]] = result["mae"]

    return {"delivery_date": day, "mae": results}


# --- check ------------------------------------------------------------------


def check_published(store: Store, target: date) -> dict:
    """The service promise: tomorrow's forecast is published by the deadline."""
    published = store.get_json(keys.published(target.isoformat())) is not None
    metrics.emit({"ForecastMissing": 0 if published else 1})
    if not published:
        log.error("no published forecast for %s at the deadline", target)
    return {"delivery_date": target.isoformat(), "published": published}


# --- backfill & report ------------------------------------------------------


def backfill(store: Store, client: SmardClient, start: date, end: date, settings: Settings) -> dict:
    """Replay the service over past days, as it would have run each morning.

    Forecasts are marked ``mode: backfill`` and never published, so the live
    track record stays separate from the replayed one.
    """
    lookback = max((start - day).days for model in MODELS.values() for day in model.input_days(start))
    ingest(store, client, start - timedelta(days=lookback), end, fetched_on=berlin_today(), settings=settings)

    scored = {}
    for target in _days(start, end):
        as_of = datetime.combine(target - timedelta(days=1), time(9, 0), BERLIN)
        forecast(store, target, settings, now=as_of, mode="backfill")
        try:
            scored[target.isoformat()] = score(store, target, settings, now=as_of)["mae"]
        except InputsNotReady:
            scored[target.isoformat()] = "pending"
    return scored


def report(store: Store, start: date, end: date) -> dict[str, dict]:
    """Mean error per model over ``start..end`` - the champion/challenger table."""
    rows: dict[str, list[dict]] = defaultdict(list)
    for day in _days(start, end):
        for key in store.list_keys(f"scores/{day.isoformat()}/"):
            result = store.get_json(key)
            rows[result["model"]].append(result)

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 2)

    return {
        model: {
            "days": len(results),
            "live_days": sum(r["mode"] == "live" for r in results),
            "mae": mean([r["mae"] for r in results]),
            "rmse": mean([r["rmse"] for r in results]),
            "bias": mean([r["bias"] for r in results]),
        }
        for model, results in sorted(rows.items())
    }
