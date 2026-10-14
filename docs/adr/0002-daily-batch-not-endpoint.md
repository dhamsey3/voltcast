# 2. A daily batch forecast, no real-time endpoint

Date: 2026-10-14 · Status: accepted

## Context

The auction takes bids once a day, until 12:00 Berlin, for all 96 slots of the
next day. A forecast is useful only if it exists before then. Nobody needs a
fresh prediction on request.

## Decision

Produce the forecast once a day on a schedule and publish it as a file
(`published/<date>.json`, plus `published/latest.json`). Don't run an
always-on inference endpoint.

## Consequences

- No idle endpoint billed by the hour; the whole service costs a few dollars a month.
- SageMaker Model Monitor, which captures traffic from real-time endpoints, doesn't fit.
  Monitoring compares each forecast with the cleared prices the same afternoon.
  That checks real accuracy instead of only estimating drift.
- If a consumer ever needs an API, a thin read-only API over the published files is enough.
