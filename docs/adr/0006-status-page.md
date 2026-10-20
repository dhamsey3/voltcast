# 6. A static status page on GitHub Pages; the bill from AWS Budgets

Date: 2026-10-16 · Status: accepted

## Context

The service's record lives in a private S3 bucket. Anyone judging it, whether
a reader of the README or a hiring manager, should be able to see the latest
forecast against the cleared price, the running error, what is deployed, and
what it costs, without AWS access. The page has to cost close to nothing:
the whole service runs at about 1 USD a month.

## Decision

- **A static page, rebuilt twice a day** by a scheduled GitHub Actions
  workflow, after the 10:15 deadline check and after the 14:30 scoring run.
  `python -m voltcast status` reads the store into `status.json` and renders
  one self-contained `index.html` from it: inline CSS and SVG, no external
  assets, every value in a table as well as a chart.
- **GitHub Pages hosts it.** The repo is public, so hosting and the
  workflow's minutes are free. Nothing new is exposed in AWS: no public
  bucket and no CDN.
- **A read-only OIDC role**, trusted from `main` only, reads just what the page
  shows: published forecasts, scores and cleared prices, decrypted through S3.
  It can't read raw snapshots or the challengers' unpublished forecasts, and
  it can't write anything.
- **The bill comes from an AWS Budget**, not Cost Explorer. Cost Explorer
  charges 0.01 USD per request, so two builds a day would add 0.30 to 0.60 USD
  a month, a third or more of the bill. The Budgets API is free, and the same
  budget emails on-call when actual or forecast spend passes 5 USD, which
  makes the cost line in the README's promise table enforced rather than
  hoped for.

## Consequences

- The page can be up to a few hours stale, and GitHub's schedule can run late
  under load. The service's own promises are enforced by CloudWatch alarms, not
  by this page.
- The budget is account-wide. That is accurate while this account runs only
  voltcast. Tracking voltcast alone needs the `project` tag activated as a
  cost allocation tag, which only applies from activation onward.
- GitHub pauses scheduled workflows after 60 days without commits. A manual
  run starts them again.
- Only live forecasts appear. The backfill replay stays in `voltcast report`
  and the README, so the live record is never mixed with hindsight.

## Update, 2026-10-19: hourly rebuilds

In the first days live, GitHub started the two scheduled runs 3 to 4 hours
late (09:30 UTC ran at about 13:20, 14:15 at about 17:20). For most of each
morning the page didn't show that day's forecast. The workflow now runs
hourly from 07:17 to 18:17 UTC, so a late start costs about an hour. The
extra runs are free: a handful of S3 reads, a free Budgets API call, and
free Actions minutes on a public repo.

## Update, 2026-10-20: the pipeline starts the rebuild

Hourly schedules didn't help: in its first day GitHub started 2 of the
roughly 17 scheduled runs, hours late. The page no longer depends on GitHub's
scheduler. When a daily run finishes, and once after the 10:15 deadline check,
a small Lambda (`voltcast-status-trigger`, same code bundle) asks GitHub to run
the workflow through its API. A daily schedule stays as a fallback.

- The token is a fine-grained GitHub token limited to this repo's Actions,
  kept in an SSM SecureString that is created by hand. It never passes through
  Terraform state, CI or the repo. SSM standard parameters are free. An
  EventBridge API destination would have needed a Secrets Manager secret
  (0.40 USD a month, about a third of the bill).
- A failed dispatch fails the Lambda and raises `status-trigger-failed`, so an
  expired token shows up as an email instead of a quietly stale page.
- The pipeline Lambda doesn't know the page exists: the trigger reacts to Step
  Functions events.
