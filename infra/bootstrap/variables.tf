variable "aws_region" {
  type    = string
  default = "eu-west-2" # London
}

variable "github_repo" {
  type        = string
  description = "GitHub repository allowed to deploy, as owner/name."

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repo))
    error_message = "Use the form owner/name."
  }
}

variable "budget_email" {
  type        = string
  description = "Where AWS Budgets sends cost alerts."
}

variable "monthly_budget_usd" {
  type        = number
  default     = 10
  description = "Monthly budget. Alerts fire at $1 actual spend, 100% actual, and 100% forecast."
}

variable "create_github_oidc_provider" {
  type        = bool
  default     = true
  description = "Set false if this AWS account already has the GitHub OIDC provider."
}
