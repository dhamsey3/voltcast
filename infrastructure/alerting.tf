# Two alarms cover the service promise (docs/runbook.md says what to do):
#   run-failed        - a daily run failed or timed out
#   forecast-missing  - no published forecast at the deadline

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "run_failed" {
  alarm_name          = "${var.project}-run-failed"
  alarm_description   = "A daily forecast/score run failed or timed out. See docs/runbook.md#run-failed"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "broken"
    expression  = "failed + timed_out"
    label       = "Failed or timed-out runs"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = { failed = "ExecutionsFailed", timed_out = "ExecutionsTimedOut" }
    content {
      id = metric_query.key
      metric {
        namespace   = "AWS/States"
        metric_name = metric_query.value
        dimensions  = { StateMachineArn = aws_sfn_state_machine.daily.arn }
        period      = 300
        stat        = "Sum"
      }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "forecast_missing" {
  alarm_name          = "${var.project}-forecast-missing"
  alarm_description   = "Tomorrow's forecast was not published by the deadline. See docs/runbook.md#forecast-missing"
  namespace           = local.metrics_namespace
  metric_name         = "ForecastMissing"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
