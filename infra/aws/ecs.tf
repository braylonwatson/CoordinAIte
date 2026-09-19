resource "aws_ecr_repository" "api" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}
resource "aws_ecs_cluster" "main" {
  name = var.name
}
resource "aws_cloudwatch_log_group" "tasks" {
  name              = "/ecs/${var.name}"
  retention_in_days = 14
}
locals {
  common_environment = [
    { name = "APP_ENV", value = "production" },
    { name = "DATABASE_HOST", value = aws_db_instance.main.address },
    { name = "DATABASE_NAME", value = aws_db_instance.main.db_name },
    { name = "DATABASE_SSLMODE", value = "verify-full" },
    { name = "DATABASE_SSLROOTCERT", value = "/app/certs/rds-bundle.pem" },
    { name = "FRONTEND_URL", value = var.frontend_url },
    { name = "CORS_ORIGINS", value = join(",", distinct(concat([var.frontend_url], var.additional_frontend_origins))) },
    { name = "AUTH_COOKIE_SECURE", value = "true" },
    { name = "AUTH_COOKIE_SAMESITE", value = "lax" },
    { name = "AUTH_COOKIE_PATH", value = "/api/auth" },
  ]
  application_secrets = [
    for name, key in {
      DATABASE_PASSWORD     = "database_password"
      JWT_SECRET_KEY        = "jwt_secret_key"
      STRIPE_SECRET_KEY     = "stripe_secret_key"
      STRIPE_PRICE_ID_TIER2 = "stripe_price_id_tier2"
      STRIPE_WEBHOOK_SECRET = "stripe_webhook_secret"
    } : { name = name, valueFrom = "${aws_secretsmanager_secret.application.arn}:${key}::" }
  ]
  logging = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.tasks.name
      awslogs-region        = var.region
      awslogs-stream-prefix = "release"
    }
  }
}
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution["api"].arn
  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name                   = "api"
    image                  = "${aws_ecr_repository.api.repository_url}:bootstrap"
    essential              = true
    readonlyRootFilesystem = true
    user                   = "10001"
    portMappings           = [{ containerPort = 8000, protocol = "tcp" }]
    environment = concat(local.common_environment, [
      { name = "DATABASE_USER", value = "coordinaite_app" },
      { name = "REALTIME_ENABLED", value = tostring(var.realtime_enabled) }
    ])
    secrets          = local.application_secrets
    logConfiguration = local.logging
    stopTimeout      = 30
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 120
    }
  }])
}
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution["migrate"].arn
  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name                   = "migrate"
    image                  = "${aws_ecr_repository.api.repository_url}:bootstrap"
    essential              = true
    readonlyRootFilesystem = true
    user                   = "10001"
    command                = ["python", "scripts/migrate.py"]
    environment = concat(local.common_environment, [
      { name = "DATABASE_USER", value = aws_db_instance.main.username },
      { name = "APPLICATION_DATABASE_USER", value = "coordinaite_app" }
    ])
    secrets = [
      { name = "DATABASE_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
      { name = "APPLICATION_DATABASE_PASSWORD", valueFrom = "${aws_secretsmanager_secret.application.arn}:database_password::" },
    ]
    logConfiguration = local.logging
  }])
}
resource "aws_ecs_service" "api" {
  name            = var.name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  # First release initializes secrets, runs migrations, then starts one task.
  desired_count                      = 0
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  health_check_grace_period_seconds  = 120
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.tasks[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
  load_balancer {
    container_name   = "api"
    container_port   = 8000
    target_group_arn = aws_lb_target_group.api.arn
  }
  dynamic "load_balancer" {
    for_each = var.realtime_enabled ? [1] : []
    content {
      container_name   = "api"
      container_port   = 8000
      target_group_arn = aws_lb_target_group.realtime[0].arn
    }
  }
  depends_on = [aws_lb_listener.api, aws_iam_role_policy.execution, aws_lb_listener_rule.realtime]
  lifecycle {
    # The release script owns application revisions and task count.
    ignore_changes = [task_definition, desired_count]
  }
}
