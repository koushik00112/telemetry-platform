resource "aws_ecs_cluster" "main" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "disabled" # costs extra; app metrics + ALB/RDS metrics cover the demo
  }
}

resource "aws_cloudwatch_log_group" "app" {
  for_each          = toset(["api", "worker", "migrate"])
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = 14
}

# --- IAM -------------------------------------------------------------------
data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by the ECS agent to pull the image, write logs and inject secrets.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.db_password.arn,
      aws_secretsmanager_secret.admin_token.arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# The app itself calls no AWS APIs, so its task role has no permissions.
resource "aws_iam_role" "task" {
  name               = "${var.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

# --- Task definitions --------------------------------------------------------
locals {
  image = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  common_env = [
    { name = "ENVIRONMENT", value = "production" },
    { name = "DB_HOST", value = aws_db_instance.main.address },
    { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
    { name = "DB_NAME", value = aws_db_instance.main.db_name },
    { name = "DB_USER", value = aws_db_instance.main.username },
    { name = "DB_SSLMODE", value = "require" },
    { name = "LOG_JSON", value = "true" },
  ]

  common_secrets = [
    { name = "DB_PASSWORD", valueFrom = aws_secretsmanager_secret.db_password.arn },
    { name = "ADMIN_TOKEN", valueFrom = aws_secretsmanager_secret.admin_token.arn },
  ]

  containers = {
    api = {
      command      = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    }
    worker = {
      command      = ["python", "-m", "app.worker"]
      portMappings = []
    }
    migrate = {
      command      = ["alembic", "upgrade", "head"]
      portMappings = []
    }
  }
}

resource "aws_ecs_task_definition" "app" {
  for_each                 = local.containers
  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64" # Graviton: about 20% cheaper than x86 on Fargate
  }

  container_definitions = jsonencode([{
    name                   = each.key
    image                  = local.image
    essential              = true
    command                = each.value.command
    portMappings           = each.value.portMappings
    environment            = local.common_env
    secrets                = local.common_secrets
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app[each.key].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = each.key
      }
    }
  }])
}

# --- Services ----------------------------------------------------------------
resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app["api"].arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 30

  deployment_circuit_breaker {
    enable   = true
    rollback = true # a deploy that never gets healthy rolls back on its own
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  # The deploy workflow registers new task definitions; don't let Terraform roll them back.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app["worker"].arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  # One worker is the supported setup (ADR 0002), so stop the old one before starting the new.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

# Everything the deploy workflow needs, in one place, so no IDs are copied by hand.
resource "aws_ssm_parameter" "deploy_config" {
  name = "/${var.name}/deploy-config"
  type = "String"
  value = jsonencode({
    cluster        = aws_ecs_cluster.main.name
    ecr_repository = aws_ecr_repository.app.repository_url
    subnets        = aws_subnet.public[*].id
    security_group = aws_security_group.tasks.id
    services       = { api = aws_ecs_service.api.name, worker = aws_ecs_service.worker.name }
    task_families  = { for k, td in aws_ecs_task_definition.app : k => td.family }
    migrate_log    = aws_cloudwatch_log_group.app["migrate"].name
    base_url       = local.base_url
  })
}
