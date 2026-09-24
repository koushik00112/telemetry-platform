output "state_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "ci_build_role_arn" {
  description = "GitHub repo variable AWS_BUILD_ROLE_ARN"
  value       = aws_iam_role.ci_build.arn
}

output "ci_deploy_role_arn" {
  description = "GitHub environment 'production' variable AWS_DEPLOY_ROLE_ARN"
  value       = aws_iam_role.ci_deploy.arn
}
