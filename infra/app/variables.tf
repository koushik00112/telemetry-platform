variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "name" {
  type    = string
  default = "telemetry"
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Only used for the first apply. After that, the deploy workflow owns the image."
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Optional email for CloudWatch alarms. Leave empty to skip."
}

variable "certificate_arn" {
  type        = string
  default     = ""
  description = "Optional ACM certificate. If set, the ALB serves HTTPS and redirects HTTP."
}

variable "demo_mode" {
  type        = bool
  default     = true
  description = "true: no deletion protection or final snapshot, so `terraform destroy` is one step."
}
