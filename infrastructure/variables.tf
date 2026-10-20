variable "aws_region" {
  description = "Region for every resource. Frankfurt keeps the data in Germany."
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Name prefix for resources"
  type        = string
  default     = "voltcast"
}

variable "code_version" {
  description = "Git SHA of the deployed code, stamped on every forecast for lineage"
  type        = string
  default     = "unknown"
}

variable "alert_email" {
  description = "Where alarms go. Empty disables the email subscription."
  type        = string
  default     = ""
  # The repo and its Actions logs are public; keep the address out of plans.
  sensitive = true
}

variable "monthly_budget_usd" {
  description = "Monthly AWS spend that alerts on-call, on actual or forecast spend (budget.tf)"
  type        = number
  default     = 5
}

# Promotion is a reviewed change to these two values - see docs/adr/0003.
variable "champion" {
  description = "Model whose forecast is published"
  type        = string
  default     = "naive_1d"
}

variable "challengers" {
  description = "Models run in shadow and scored, never published"
  type        = list(string)
  default     = ["seasonal_naive_7d"]
}

# Times are Europe/Berlin. The auction closes at 12:00 for the next day.
variable "forecast_schedule" {
  description = "When the forecast run starts"
  type        = string
  default     = "cron(0 9 * * ? *)"
}

variable "check_schedule" {
  description = "Deadline for the published forecast; missing means an alert"
  type        = string
  default     = "cron(15 10 * * ? *)"
}

variable "score_schedule" {
  description = "When scoring starts; auction results usually appear around 14:00"
  type        = string
  default     = "cron(30 14 * * ? *)"
}

variable "upstream_wait_attempts" {
  description = "How many 15-minute waits for late upstream data before failing"
  type        = number
  default     = 12
}

# The status page rebuild (status_trigger.tf).
variable "status_refresh_schedule" {
  description = "When the page is rebuilt to show the deadline check's verdict"
  type        = string
  default     = "cron(20 10 * * ? *)"
}

variable "status_token_parameter" {
  description = "SSM SecureString holding a GitHub token that may dispatch the status workflow"
  type        = string
  default     = "/voltcast/github-dispatch-token"
}

variable "github_repository" {
  description = "owner/name of the repo whose status workflow builds the page"
  type        = string
  default     = "dhamsey3/voltcast"
}
