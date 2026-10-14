# One small Lambda runs every pipeline step; Step Functions decides which.
# `make build` assembles ../build/lambda (our package + tzdata).

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../build/lambda"
  output_path = "${path.module}/../build/lambda.zip"
}

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/aws/lambda/${var.project}-pipeline"
  retention_in_days = 30
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "${var.project}-pipeline"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Least privilege: its own log group, its own bucket, its own key. Metrics
# go out through log lines (Embedded Metric Format), so no cloudwatch:* here.
data "aws_iam_policy_document" "pipeline" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.pipeline.arn}:*"]
  }
  statement {
    sid       = "ReadWriteState"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    # Needed so a missing key reads as NoSuchKey rather than AccessDenied.
    sid       = "ListState"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
  statement {
    sid       = "UseDataKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "pipeline"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}

resource "aws_lambda_function" "pipeline" {
  function_name    = "${var.project}-pipeline"
  role             = aws_iam_role.pipeline.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "voltcast.handler.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 256
  timeout          = 120

  environment {
    variables = {
      DATA_STORE        = "s3://${aws_s3_bucket.data.id}"
      CODE_VERSION      = var.code_version
      CHAMPION          = var.champion
      CHALLENGERS       = join(",", var.challengers)
      METRICS_NAMESPACE = local.metrics_namespace
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.pipeline.name
  }

  depends_on = [aws_iam_role_policy.pipeline]
}

locals {
  metrics_namespace = "Voltcast"
}
