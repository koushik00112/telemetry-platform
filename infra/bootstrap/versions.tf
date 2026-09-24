terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.90"
    }
  }
  # Bootstrap creates the remote state bucket, so its own state stays local.
  # Keep terraform.tfstate from this folder somewhere safe; it is gitignored.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "telemetry-platform"
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}
