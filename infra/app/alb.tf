resource "aws_lb" "main" {
  name                       = var.name
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = !var.demo_mode
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 15

  # /livez, not /healthz: if the database goes down, every task would fail a DB-backed
  # check and ECS would restart them all in a loop, making recovery slower (ADR 0003).
  health_check {
    path                = "/livez"
    matcher             = "200"
    interval            = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
  }
}

locals {
  https    = var.certificate_arn != ""
  base_url = local.https ? "https://${aws_lb.main.dns_name}" : "http://${aws_lb.main.dns_name}"
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.https ? "redirect" : "forward"

    target_group_arn = local.https ? null : aws_lb_target_group.api.arn

    dynamic "redirect" {
      for_each = local.https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = local.https ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# /metrics is for internal scraping only; never serve it publicly.
resource "aws_lb_listener_rule" "block_metrics" {
  listener_arn = local.https ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/metrics", "/metrics/*"]
    }
  }

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"detail\":\"Not Found\"}"
      status_code  = "404"
    }
  }
}
