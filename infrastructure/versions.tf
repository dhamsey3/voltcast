terraform {
  required_version = ">= 1.5.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Shared state bucket + lock table from the aws-oidc-bootstrap repo.
  # Copy backend.hcl.example to backend.hcl and run `make plan`.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project    = var.project
      repository = "voltcast"
      managed_by = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
