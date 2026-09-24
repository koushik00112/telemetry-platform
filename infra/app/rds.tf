resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "main" {
  name   = var.name
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "500" # log queries slower than 500 ms
  }
}

resource "aws_db_instance" "main" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "telemetry"
  username = "telemetry"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false # single AZ keeps cost down; see ADR 0003

  backup_retention_period    = 1
  auto_minor_version_upgrade = true
  deletion_protection        = !var.demo_mode
  skip_final_snapshot        = var.demo_mode
  final_snapshot_identifier  = var.demo_mode ? null : "${var.name}-final"
  apply_immediately          = true
}
