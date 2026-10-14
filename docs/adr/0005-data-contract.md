# 5. Missing data waits, wrong data stops, hindsight is refused

Date: 2026-10-14 · Status: accepted

## Context

Upstream data fails in two different ways that need opposite responses:

- **Late**: the auction result or SMARD's publication of it is delayed. Waiting fixes it.
- **Wrong**: slots that don't fit the calendar, duplicates, or prices outside the auction limits.
  Waiting doesn't fix it, and publishing a forecast built on it is worse than publishing nothing.

A third risk is quieter. A "live" forecast made after the auction closed would
be hindsight, and it would flatter the track record.

## Decision

The contract for one delivery day (`src/voltcast/contract.py`):

- Exactly the 15-minute slots of the Berlin day: 96, or **92 / 100** on clock-change days.
- No duplicate timestamps, nothing off the 15-minute grid.
- Prices within the SDAC harmonised limits, **-500 to +4000 EUR/MWh**. The replay
  saw -499.99, so the floor is real.

Failures map to exceptions the orchestrator understands:

| Exception | Meaning | Response |
|---|---|---|
| `InputsNotReady` | data not published yet | wait 15 min, re-ingest, retry |
| `SmardUnavailable` | network / bad response | short backoff retry |
| `ContractViolation` | data present but wrong | fail now, alert a human |
| `TooLate` | live forecast after 12:00 gate closure | fail now; use `backfill` for past days |

## Consequences

- Revisions to already-curated days are allowed but logged (`DaysRevised`
  metric). S3 versioning keeps the old value, and every forecast records the
  sha256 of the inputs it used.
- If the auction limits change, the contract fails loudly until
  `PRICE_FLOOR`/`PRICE_CAP` are updated. That is deliberate.
