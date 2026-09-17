resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.name}-"
  family      = "postgres17"
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
}
resource "aws_db_instance" "main" {
  identifier                  = var.name
  engine                      = "postgres"
  engine_version              = "17"
  engine_lifecycle_support    = "open-source-rds-extended-support-disabled"
  instance_class              = var.db_instance_class
  db_name                     = "coordinaite"
  username                    = "coordinaite_admin"
  manage_master_user_password = true
  allocated_storage           = 20
  max_allocated_storage       = 30
  storage_type                = "gp3"
  storage_encrypted           = true
  publicly_accessible         = false
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.database.id]
  parameter_group_name        = aws_db_parameter_group.main.name
  multi_az                    = var.db_multi_az
  backup_retention_period     = 7
  copy_tags_to_snapshot       = true
  auto_minor_version_upgrade  = true
  deletion_protection         = var.db_deletion_protection
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${var.name}-final"
  delete_automated_backups    = false
}

# Only metadata is in Terraform. scripts/aws_setup.py initializes values directly
# in Secrets Manager, keeping the database password and JWT key out of state.
resource "aws_secretsmanager_secret" "application" {
  name                    = "${var.name}/application"
  recovery_window_in_days = 7
}
