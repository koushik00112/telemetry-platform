output "base_url" {
  value = local.base_url
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "admin_token_secret" {
  description = "Read with: aws secretsmanager get-secret-value --secret-id <this> --query SecretString --output text"
  value       = aws_secretsmanager_secret.admin_token.name
}
