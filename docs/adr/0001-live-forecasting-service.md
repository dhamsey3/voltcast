# 1. A live forecasting service, not a synthetic-dataset pipeline

Date: 2026-10-14 · Status: accepted

## Context

The first plan for this repo was predictive maintenance on the AI4I 2020
dataset, built as a tour of SageMaker features. AI4I is synthetic, so drift had
to be simulated and nothing could ever be checked against reality. The result
would look like the AWS reference workshop that many portfolios already copy.

## Decision

Build a service that runs every day on real, open data and is graded every
day: forecast the German/Luxembourg day-ahead electricity price for each
15-minute slot of the next day, publish it before the 12:00 auction, and score
it against the cleared prices that afternoon.

Energy was picked because it is a top-two hiring sector in both Germany and
Switzerland. It is also tied to manufacturing, because energy-heavy plants
schedule around price. Finally, its data is local, open and arrives daily.

## Consequences

- The evidence is a track record (uptime, accuracy over time, incidents), not a notebook.
- Drift, late data, source revisions and clock changes are real problems to handle, not simulations.
- The repo name no longer matches; renaming is cosmetic and can wait.
