# 3. Naive models first; the champion is chosen by evidence

Date: 2026-10-14 · Status: accepted

## Context

A clever model on top of a pipeline that isn't proven is the usual way these
projects stall. Following rule #4 of Google's *Rules of ML*, the first model
should be simple and the infrastructure right. Any learned model must also
beat a baseline before it means anything.

## Decision

Phase 1 ships two seasonal-naive models that copy a past day's price for the
same Berlin wall-clock slot:

| Model | Rule | Inputs |
|---|---|---|
| `naive_1d` | the most recent published day | t-1 |
| `seasonal_naive_7d` | same weekday last week | t-7 |

The pipeline runs all models every day: one **champion** (published) and the
**challengers** (shadow, scored, never published).

The first champion was chosen by replaying the service over every day since
the auction moved to 15-minute products (2025-10-01 to 2026-10-15, 380 days,
SMARD data):

| Model | MAE (EUR/MWh) | RMSE | Bias |
|---|---|---|---|
| `naive_1d` | **30.75** | **40.66** | -0.13 |
| `seasonal_naive_7d` | 38.58 | 49.34 | -0.71 |

`naive_1d` wins on every weekday except Saturday (tie) and Monday (both bad,
42-44), where yesterday's prices are a poor guide because the day type
changes. That gives a natural next challenger: a day-type-aware naive model.

## Consequences

- Promotion is a reviewed change to the `champion` / `challengers` Terraform
  variables, with `python -m dayahead report` output attached to the PR.
- These numbers are a replay. The live track record starts on the first
  deployed day and is reported separately (`live_days` in the report).
- Any future ML model has a clear bar to clear: ~31 EUR/MWh MAE.
