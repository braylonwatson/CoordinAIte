# Optional direct TLS route. The existing HTTP API Gateway is not a WebSocket
# tunnel. Keep the private REST ALB and expose only this explicit live path.
variable "realtime_enabled" {
  type        = bool
  default     = false
  description = "Provision an additional public TLS ALB for live predictions. Adds AWS cost."
}
variable "realtime_domain" {
  type        = string
  default     = ""
  description = "Owned DNS name, for example live.coordinaite.ai."
}
variable "realtime_zone_id" {
  type        = string
  default     = ""
  description = "Existing public Route 53 hosted zone containing realtime_domain."
}

resource "aws_security_group" "realtime" {
  count       = var.realtime_enabled ? 1 : 0
  name_prefix = "${var.name}-live-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_vpc_security_group_ingress_rule" "realtime_https" {
  count             = var.realtime_enabled ? 1 : 0
  security_group_id = aws_security_group.realtime[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_egress_rule" "realtime_to_tasks" {
  count                        = var.realtime_enabled ? 1 : 0
  security_group_id            = aws_security_group.realtime[0].id
  referenced_security_group_id = aws_security_group.tasks.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
resource "aws_vpc_security_group_ingress_rule" "tasks_from_realtime" {
  count                        = var.realtime_enabled ? 1 : 0
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = aws_security_group.realtime[0].id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
resource "aws_acm_certificate" "realtime" {
  count             = var.realtime_enabled ? 1 : 0
  domain_name       = var.realtime_domain
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = var.realtime_domain != "" && var.realtime_zone_id != ""
      error_message = "Live predictions require realtime_domain and realtime_zone_id."
    }
  }
}
resource "aws_route53_record" "realtime_validation" {
  for_each = var.realtime_enabled ? {
    for option in aws_acm_certificate.realtime[0].domain_validation_options : option.domain_name => option
  } : {}
  zone_id = var.realtime_zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 60
}
resource "aws_acm_certificate_validation" "realtime" {
  count                   = var.realtime_enabled ? 1 : 0
  certificate_arn         = aws_acm_certificate.realtime[0].arn
  validation_record_fqdns = [for record in aws_route53_record.realtime_validation : record.fqdn]
}
resource "aws_lb" "realtime" {
  count                      = var.realtime_enabled ? 1 : 0
  name                       = "${var.name}-live"
  internal                   = false
  load_balancer_type         = "application"
  subnets                    = aws_subnet.tasks[*].id
  security_groups            = [aws_security_group.realtime[0].id]
  drop_invalid_header_fields = true
  idle_timeout               = 120
}
resource "aws_lb_target_group" "realtime" {
  count                = var.realtime_enabled ? 1 : 0
  name                 = "${var.name}-live"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30
  health_check {
    path                = "/health/ready"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
  }
}
resource "aws_lb_listener" "realtime" {
  count             = var.realtime_enabled ? 1 : 0
  load_balancer_arn = aws_lb.realtime[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.realtime[0].certificate_arn
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      status_code  = "404"
      message_body = "Not found"
    }
  }
}
resource "aws_lb_listener_rule" "realtime" {
  count        = var.realtime_enabled ? 1 : 0
  listener_arn = aws_lb_listener.realtime[0].arn
  priority     = 1
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.realtime[0].arn
  }
  condition {
    path_pattern {
      values = ["/ws/predictions"]
    }
  }
}
resource "aws_route53_record" "realtime" {
  count   = var.realtime_enabled ? 1 : 0
  zone_id = var.realtime_zone_id
  name    = var.realtime_domain
  type    = "A"
  alias {
    name                   = aws_lb.realtime[0].dns_name
    zone_id                = aws_lb.realtime[0].zone_id
    evaluate_target_health = true
  }
}
output "realtime_url" {
  value = var.realtime_enabled ? "wss://${var.realtime_domain}/ws/predictions" : null
}
