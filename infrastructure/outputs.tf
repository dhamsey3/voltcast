output "data_bucket" {
  description = "Pipeline state; published forecasts live under published/"
  value       = aws_s3_bucket.data.id
}

output "state_machine_arn" {
  description = "Start a manual run: aws stepfunctions start-execution --state-machine-arn <this> --input '{\"job\":\"forecast\"}'"
  value       = aws_sfn_state_machine.daily.arn
}

output "lambda_function" {
  value = aws_lambda_function.pipeline.function_name
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "budget_name" {
  description = "Read by the status page for its bill section"
  value       = aws_budgets_budget.monthly.name
}
