# The status page follows the pipeline: when a daily run finishes (succeeded or
# not), and once after the deadline check, a small Lambda asks GitHub to run
# the status workflow. GitHub's own schedule ran hours late or not at all
# (docs/adr/0006-status-page.md). Same code bundle as the pipeline, different
# entry point (src/voltcast/trigger.py).
#
# The GitHub token is an SSM SecureString created by hand (docs/runbook.md),
# never by Terraform, so it stays out of the state file and CI. Only its name
# appears here.


resource "aws_cloudwatch_log_group" "status_trigger" {
  name              = "/aws/lambda/${var.project}-status-trigger"
  retention_in_days = 30
}

resource "aws_iam_role" "status_trigger" {
  name               = "${var.project}-status-trigger"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Its own log group and the one parameter. The parameter uses the AWS-managed
# aws/ssm key, whose key policy already allows decryption through SSM.
resource "aws_iam_role_policy" "status_trigger" {
  name = "status-trigger"
  role = aws_iam_role.status_trigger.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.status_trigger.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.status_token_parameter}"
      },
    ]
  })
}

resource "aws_lambda_function" "status_trigger" {
  function_name    = "${var.project}-status-trigger"
  role             = aws_iam_role.status_trigger.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "voltcast.trigger.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      TOKEN_PARAMETER   = var.status_token_parameter
      GITHUB_REPOSITORY = var.github_repository
      WORKFLOW_FILE     = "status.yml"
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.status_trigger.name
  }

  depends_on = [aws_iam_role_policy.status_trigger]
}

# Every finished daily run, whatever its outcome: a failure changes the page too.
resource "aws_cloudwatch_event_rule" "run_finished" {
  name        = "${var.project}-run-finished"
  description = "A voltcast daily run finished; rebuild the status page"
  event_pattern = jsonencode({
    source        = ["aws.states"]
    "detail-type" = ["Step Functions Execution Status Change"]
    detail = {
      stateMachineArn = [aws_sfn_state_machine.daily.arn]
      status          = ["SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "run_finished" {
  rule = aws_cloudwatch_event_rule.run_finished.name
  arn  = aws_lambda_function.status_trigger.arn
}

resource "aws_lambda_permission" "run_finished" {
  statement_id  = "rebuild-status-page"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.status_trigger.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.run_finished.arn
}

# Just after the 10:15 deadline check, so a missing forecast shows as
# missing within minutes, not at the next run.
resource "aws_scheduler_schedule" "status_after_deadline" {
  name                         = "${var.project}-status-after-deadline"
  description                  = "Rebuild the status page after the deadline check"
  schedule_expression          = var.status_refresh_schedule
  schedule_expression_timezone = "Europe/Berlin"
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_lambda_function.status_trigger.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ reason = "deadline" })
  }
}

# Not a forecast problem, but the only sign of an expired or missing token.
resource "aws_cloudwatch_metric_alarm" "status_trigger_failed" {
  alarm_name          = "${var.project}-status-trigger-failed"
  alarm_description   = "The status page couldn't be rebuilt: GitHub refused the dispatch. See docs/runbook.md#status-trigger-failed"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.status_trigger.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
