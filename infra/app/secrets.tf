# Generated here, so the values live in Terraform state. The state bucket is private,
# encrypted and TLS-only (see ../bootstrap). Accepted trade-off, noted in docs/threat-model.md.
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "admin_token" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.name}/db-password"
  recovery_window_in_days = var.demo_mode ? 0 : 7
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db.result
}

resource "aws_secretsmanager_secret" "admin_token" {
  name                    = "${var.name}/admin-token"
  recovery_window_in_days = var.demo_mode ? 0 : 7
}

resource "aws_secretsmanager_secret_version" "admin_token" {
  secret_id     = aws_secretsmanager_secret.admin_token.id
  secret_string = random_password.admin_token.result
}
