# Daily run: ingest -> forecast|score. Late upstream data (InputsNotReady)
# means wait 15 minutes, re-ingest and try again; wrong data
# (ContractViolation) or a closed auction (TooLate) fails the run at once.

locals {
  lambda_service_errors = [
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
  ]

  daily_definition = {
    Comment        = "Ingest from SMARD, then forecast or score. Input: {\"job\": \"forecast\" | \"score\"}"
    StartAt        = "Init"
    TimeoutSeconds = 4 * 3600
    States = {
      Init = {
        Type       = "Pass"
        Parameters = { "job.$" = "$.job", attempt = 0 }
        Next       = "Ingest"
      }
      Ingest = {
        Type           = "Task"
        Resource       = "arn:aws:states:::lambda:invoke"
        Parameters     = { FunctionName = aws_lambda_function.pipeline.arn, Payload = { step = "ingest" } }
        ResultSelector = { "summary.$" = "$.Payload" }
        ResultPath     = "$.ingest"
        Retry = [
          { ErrorEquals = ["SmardUnavailable"], IntervalSeconds = 60, MaxAttempts = 4, BackoffRate = 2 },
          { ErrorEquals = local.lambda_service_errors, IntervalSeconds = 5, MaxAttempts = 3, BackoffRate = 2 },
        ]
        Next = "Run"
      }
      Run = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.pipeline.arn
          # Pin the target day to when the run started, not when a retry happens.
          Payload = { "step.$" = "$.job", "run_started_at.$" = "$$.Execution.StartTime" }
        }
        ResultSelector = { "summary.$" = "$.Payload" }
        ResultPath     = "$.result"
        Retry = [
          { ErrorEquals = local.lambda_service_errors, IntervalSeconds = 5, MaxAttempts = 3, BackoffRate = 2 },
        ]
        Catch = [
          { ErrorEquals = ["InputsNotReady"], ResultPath = "$.waiting_for", Next = "KeepWaiting" },
        ]
        End = true
      }
      KeepWaiting = {
        Type = "Choice"
        Choices = [
          { Variable = "$.attempt", NumericGreaterThanEquals = var.upstream_wait_attempts, Next = "InputsNeverArrived" },
        ]
        Default = "WaitForUpstream"
      }
      WaitForUpstream = {
        Type    = "Wait"
        Seconds = 900
        Next    = "CountAttempt"
      }
      CountAttempt = {
        Type       = "Pass"
        Parameters = { "job.$" = "$.job", "attempt.$" = "States.MathAdd($.attempt, 1)" }
        Next       = "Ingest"
      }
      InputsNeverArrived = {
        Type  = "Fail"
        Error = "InputsNeverArrived"
        Cause = "Upstream prices were still missing after the last retry"
      }
    }
  }
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "daily" {
  name               = "${var.project}-daily-run"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

resource "aws_iam_role_policy" "daily" {
  name = "invoke-pipeline"
  role = aws_iam_role.daily.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [aws_lambda_function.pipeline.arn, "${aws_lambda_function.pipeline.arn}:*"]
    }]
  })
}

resource "aws_sfn_state_machine" "daily" {
  name       = "${var.project}-daily"
  role_arn   = aws_iam_role.daily.arn
  definition = jsonencode(local.daily_definition)
}

# --- schedules (Europe/Berlin, so DST is handled by the scheduler) ---------

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name = "start-runs"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "states:StartExecution", Resource = aws_sfn_state_machine.daily.arn },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = [aws_lambda_function.pipeline.arn, aws_lambda_function.status_trigger.arn]
      },
    ]
  })
}

resource "aws_scheduler_schedule" "forecast" {
  name                         = "${var.project}-forecast"
  description                  = "Forecast the next delivery day before the 12:00 auction"
  schedule_expression          = var.forecast_schedule
  schedule_expression_timezone = "Europe/Berlin"
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_sfn_state_machine.daily.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ job = "forecast" })
  }
}

resource "aws_scheduler_schedule" "score" {
  name                         = "${var.project}-score"
  description                  = "Score forecasts once the auction result is published"
  schedule_expression          = var.score_schedule
  schedule_expression_timezone = "Europe/Berlin"
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_sfn_state_machine.daily.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ job = "score" })
  }
}

resource "aws_scheduler_schedule" "check" {
  name                         = "${var.project}-deadline-check"
  description                  = "Alert if tomorrow's forecast is not published by the deadline"
  schedule_expression          = var.check_schedule
  schedule_expression_timezone = "Europe/Berlin"
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_lambda_function.pipeline.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ step = "check" })
  }
}
