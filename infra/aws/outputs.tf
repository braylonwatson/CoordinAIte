output "api_url" {
  value = aws_apigatewayv2_api.api.api_endpoint
}
output "release_config" {
  description = "Non-secret settings for the release script and GitHub Actions."
  value = {
    region                  = var.region
    repository_url          = aws_ecr_repository.api.repository_url
    cluster                 = aws_ecs_cluster.main.name
    service                 = aws_ecs_service.api.name
    api_task_definition     = aws_ecs_task_definition.api.arn
    migrate_task_definition = aws_ecs_task_definition.migrate.arn
    subnet_ids              = aws_subnet.tasks[*].id
    security_group_ids      = [aws_security_group.tasks.id]
    application_secret_arn  = aws_secretsmanager_secret.application.arn
    github_role_arn         = aws_iam_role.deploy.arn
    api_url                 = aws_apigatewayv2_api.api.api_endpoint
    frontend_url            = var.frontend_url
  }
}
