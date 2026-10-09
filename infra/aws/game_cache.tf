# Optional private cache. Versions in PostgreSQL control freshness and access.
resource "aws_elasticache_subnet_group" "game" {
  count      = var.game_cache_enabled ? 1 : 0
  name       = "${var.name}-game"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "game_cache" {
  count       = var.game_cache_enabled ? 1 : 0
  name_prefix = "${var.name}-game-cache-"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "game_cache_from_tasks" {
  count                        = var.game_cache_enabled ? 1 : 0
  security_group_id            = aws_security_group.game_cache[0].id
  referenced_security_group_id = aws_security_group.tasks.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

resource "aws_vpc_security_group_egress_rule" "tasks_to_game_cache" {
  count                        = var.game_cache_enabled ? 1 : 0
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = aws_security_group.game_cache[0].id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

resource "aws_elasticache_replication_group" "game" {
  count                      = var.game_cache_enabled ? 1 : 0
  replication_group_id       = "${var.name}-game"
  description                = "Versioned active-game read cache"
  engine                     = "valkey"
  node_type                  = var.game_cache_node_type
  num_cache_clusters         = 1
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.game[0].name
  security_group_ids         = [aws_security_group.game_cache[0].id]
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  automatic_failover_enabled = false
  snapshot_retention_limit   = 0
  apply_immediately          = true
}
