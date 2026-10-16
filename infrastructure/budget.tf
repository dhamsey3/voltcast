# The cost promise as an alert: AWS Budgets emails on-call when this month's
# actual spend passes the limit, or when AWS forecasts that it will. It is
# account-wide because this account runs only voltcast (the project tag isn't
# activated for cost allocation). The status page reads the same budget for
# its bill section; the Budgets API is free, unlike Cost Explorer's.

resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = format("%.2f", var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    # Only whether an address is set is revealed here, never the address.
    for_each = nonsensitive(var.alert_email == "") ? {} : { ACTUAL = 100, FORECASTED = 100 }
    content {
      notification_type          = notification.key
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
