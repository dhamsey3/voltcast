# 4. Scheduler + Step Functions + Lambda for Phase 1; SageMaker when training needs it

Date: 2026-10-14 · Status: accepted

## Context

Phase 1 does no training. Each step fetches a few hundred kilobytes, does some
arithmetic and writes small JSON files. The hard part is operational: running
at the right Berlin time across clock changes, waiting for late upstream data,
retrying safely and alerting when the promise is missed.

## Decision

- **EventBridge Scheduler** with `Europe/Berlin` schedules: no hand-rolled UTC
  offsets that break twice a year.
- **Step Functions** for the daily run. It ingests, then forecasts or scores.
  On `InputsNotReady` it waits 15 minutes, re-ingests and retries, up to 12
  times. `ContractViolation` and `TooLate` fail the run at once.
  Every run's history is kept for audit.
- **One Lambda** (Python 3.13, arm64, standard library + tzdata) runs every step.
- **S3** (versioned, KMS) holds all state. Metrics go out as CloudWatch
  Embedded Metric Format log lines.

## Consequences

- About 2 USD a month, nearly all of it the KMS key and two alarms.
- SageMaker comes in with Phase 3, when there is a model to train, register and approve.
  It is added because training needs it, not to tick a box.
- The 2.6 MB Lambda bundle has no third-party runtime dependency beyond tzdata,
  so there are few supply-chain risks to manage.
