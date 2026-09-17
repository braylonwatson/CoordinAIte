resource "aws_lb" "api" {
  name               = var.name
  internal           = true
  load_balancer_type = "application"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.load_balancer.id]
}
resource "aws_lb_target_group" "api" {
  name                 = var.name
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
resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# API Gateway supplies an HTTPS hostname without requiring a purchased domain.
# The load balancer accepts traffic only from this private VPC link.
resource "aws_apigatewayv2_api" "api" {
  name          = var.name
  protocol_type = "HTTP"
}
resource "aws_apigatewayv2_vpc_link" "api" {
  name               = var.name
  subnet_ids         = aws_subnet.private[*].id
  security_group_ids = [aws_security_group.gateway.id]
}
resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = aws_lb_listener.api.arn
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.api.id
  payload_format_version = "1.0"
  timeout_milliseconds   = 30000
  request_parameters = {
    "overwrite:path" = "$request.path"
  }
}
resource "aws_apigatewayv2_route" "api" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}
resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/coordinaite/${var.name}/http"
  retention_in_days = 14
}
resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.gateway.arn
    format = jsonencode({
      requestId = "$context.requestId"
      method    = "$context.httpMethod"
      path      = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
    })
  }
}
