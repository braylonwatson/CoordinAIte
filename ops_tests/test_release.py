from unittest.mock import Mock, patch

import pytest

from scripts import deploy_aws


CONFIG = {
    "repository_url": "123456789012.dkr.ecr.us-east-1.amazonaws.com/coordinaite",
    "api_task_definition": "api-base",
    "migrate_task_definition": "migrate-base",
    "cluster": "coordinaite",
    "service": "coordinaite",
    "subnet_ids": ["subnet-test"],
    "security_group_ids": ["sg-test"],
    "api_url": "https://api.example.com",
}
IMAGE = CONFIG["repository_url"] + ":release-test"


def test_failed_migration_prevents_service_update():
    ecs = Mock()
    ecs.run_task.return_value = {"tasks": [{"taskArn": "migration-task"}]}
    ecs.describe_tasks.return_value = {
        "tasks": [{"containers": [{"exitCode": 1}], "stoppedReason": "migration failed"}],
    }
    with patch.object(deploy_aws, "register_release", side_effect=["api-new", "migrate-new"]):
        with pytest.raises(RuntimeError, match="Migration failed"):
            deploy_aws.deploy(ecs, CONFIG, IMAGE, 1)
    ecs.update_service.assert_not_called()


def test_stable_rollback_is_not_reported_as_success():
    ecs = Mock()
    ecs.describe_services.return_value = {
        "services": [{"taskDefinition": "api-old", "runningCount": 1}],
    }
    with patch.object(deploy_aws, "register_release", side_effect=["api-new", "migrate-new"]), \
         patch.object(deploy_aws, "run_migration"), \
         patch.object(deploy_aws, "check_health") as check:
        with pytest.raises(RuntimeError, match="rolled back"):
            deploy_aws.deploy(ecs, CONFIG, IMAGE, 1)
    check.assert_not_called()


def test_image_from_another_repository_is_rejected_before_mutations():
    ecs = Mock()
    with pytest.raises(ValueError, match="this stack"):
        deploy_aws.deploy(ecs, CONFIG, "unrelated.example.com/api:latest", 1)
    assert not ecs.mock_calls
