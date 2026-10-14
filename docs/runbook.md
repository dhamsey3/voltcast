# Runbook

All times are Europe/Berlin. The auction for day *D* closes at **12:00 on D-1**.
Results usually appear on SMARD around 14:00.

| When | What runs |
|---|---|
| 09:00 | daily run `{"job":"forecast"}`: ingest, then forecast the next open auction |
| 10:15 | deadline check: is tomorrow's forecast published? |
| 14:30 | daily run `{"job":"score"}`: ingest, then score tomorrow's forecasts |

## run-failed

A daily run failed or timed out. Open the failed execution in the Step
Functions console (state machine `dayahead-daily`) and read the error on the
failing state.

| Error | What it means | Do this |
|---|---|---|
| `InputsNeverArrived` | upstream prices still missing after 12 x 15 min | Check smard.de. If SMARD is down, wait; once the data appears, re-run (below). For a forecast after 12:00, the day is lost: record an incident. |
| `ContractViolation` | data arrived but breaks the contract | **Don't force it through.** Look at the message (which day, which check). Compare with smard.de. If the auction limits changed, update `PRICE_FLOOR`/`PRICE_CAP` in a PR. Record an incident. |
| `TooLate` | a forecast run started after gate closure | The scheduler fired late or someone re-ran it by hand. Nothing to publish. Score as normal. |
| `SmardUnavailable` | network or bad response after retries | Usually transient. Re-run. |
| anything else | a bug | Reproduce locally with `python -m dayahead --store s3://<bucket> ...`, fix, deploy, re-run. |

## forecast-missing

No `published/<tomorrow>.json` at 10:15. There are still ~100 minutes until
the auction closes.

1. Is a forecast run still waiting for data? Check the executions list. If so, it will keep trying until 12:00.
2. If no run is going, start one (below).
3. If it can't be published before 12:00, record an incident. Don't publish afterwards (`TooLate` won't let you).

## Manual actions

Start a daily run:

```bash
aws stepfunctions start-execution --state-machine-arn "$(terraform -chdir=infrastructure output -raw state_machine_arn)" --input '{"job":"forecast"}'
```

Run one step for a specific day, for example re-scoring:

```bash
aws lambda invoke --function-name dayahead-pipeline --payload '{"step":"score","delivery_date":"2026-10-16"}' out.json
```

With AWS CLI v2, add `--cli-binary-format raw-in-base64-out`.

Champion vs challenger over the last 30 days, straight from the bucket:

```bash
.venv/bin/python -m dayahead --store "s3://$(terraform -chdir=infrastructure output -raw data_bucket)" report --days 30
```

Promote a model: open a PR that swaps `champion`/`challengers` in
`infrastructure/terraform.tfvars` (or the variable defaults). Paste the report
into it and add an ADR if the reasoning is new.

## Clock-change days

Nothing to do. Delivery days have 92 slots (last Sunday of March) or 100 (last
Sunday of October). The scheduler runs on Berlin time, and the tests cover both
cases with real data.
