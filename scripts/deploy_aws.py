"""Publish registered ECS revisions only after the one-off migration succeeds."""
import argparse
import json
import time
import urllib.request
from pathlib import Path

import boto3


REGISTER_FIELDS = {
    "family", "taskRoleArn", "executionRoleArn", "networkMode", "containerDefinitions",
    "volumes", "placementConstraints", "requiresCompatibilities", "cpu", "memory",
    "pidMode", "ipcMode", "proxyConfiguration", "inferenceAccelerators",
    "ephemeralStorage", "runtimePlatform",
}


def configure_api_container(container, config):
    """Keep owner and support settings present when releases clone older task revisions."""
    environment = {item["name"]: item.get("value", "") for item in container.get("environment", [])}
    owner_emails = config.get("owner_emails") or ["braylon5watson@gmail.com"]
    if isinstance(owner_emails, str):
        owner_emails = [email.strip() for email in owner_emails.split(",") if email.strip()]
    environment.update({
        "OWNER_EMAILS": ",".join(owner_emails),
        "SUPPORT_EMAIL": config.get("support_email") or "support@coordinaite.net",
        "SMTP_HOST": config.get("smtp_host") or "smtp.gmail.com",
        "SMTP_PORT": str(config.get("smtp_port") or 587),
        "SMTP_USERNAME": config.get("smtp_username") or "support@coordinaite.net",
    })
    container["environment"] = [{"name": name, "value": value} for name, value in environment.items()]

    secret_arn = config.get("application_secret_arn")
    if not secret_arn:
        raise ValueError("release-config.json must contain application_secret_arn to inject SMTP credentials.")
    secrets = {item["name"]: item for item in container.get("secrets", [])}
    secrets["SMTP_PASSWORD"] = {
        "name": "SMTP_PASSWORD",
        "valueFrom": f"{secret_arn}:smtp_password::",
    }
    container["secrets"] = list(secrets.values())


def register_release(ecs, source, image, config, *, api=False):
    original = ecs.describe_task_definition(taskDefinition=source, include=["TAGS"])
    definition = {key: value for key, value in original["taskDefinition"].items() if key in REGISTER_FIELDS}
    for container in definition["containerDefinitions"]:
        container["image"] = image
        if api and container["name"] == "api":
            configure_api_container(container, config)
    definition["tags"] = original.get("tags", [])
    return ecs.register_task_definition(**definition)["taskDefinition"]["taskDefinitionArn"]


def run_migration(ecs, config, task_definition):
    started = ecs.run_task(
        cluster=config["cluster"], taskDefinition=task_definition, launchType="FARGATE",
        platformVersion="1.4.0",
        networkConfiguration={"awsvpcConfiguration": {
            "subnets": config["subnet_ids"], "securityGroups": config["security_group_ids"],
            "assignPublicIp": "ENABLED",
        }},
        count=1,
    )
    if started.get("failures") or not started.get("tasks"):
        raise RuntimeError(f"Migration could not start: {started.get('failures')}")
    task = started["tasks"][0]["taskArn"]
    print(f"Migration task: {task}", flush=True)
    try:
        ecs.get_waiter("tasks_stopped").wait(
            cluster=config["cluster"], tasks=[task],
            WaiterConfig={"Delay": 10, "MaxAttempts": 90},
        )
    except Exception:
        ecs.stop_task(cluster=config["cluster"], task=task, reason="Release migration wait failed")
        raise
    description = ecs.describe_tasks(cluster=config["cluster"], tasks=[task])["tasks"][0]
    containers = description.get("containers", [])
    if not containers or any(container.get("exitCode") != 0 for container in containers):
        raise RuntimeError(
            f"Migration failed ({description.get('stoppedReason')}). "
            "Inspect its CloudWatch log; the API service has not been updated."
        )


def check_health(api_url):
    last_error = None
    for attempt in range(12):
        try:
            with urllib.request.urlopen(api_url + "/health/ready", timeout=15) as response:
                payload = json.load(response)
                if response.status == 200 and payload.get("status") == "ready":
                    return
        except Exception as error:
            last_error = error
        time.sleep(5)
    raise RuntimeError(f"Public readiness check failed: {last_error}")


def deploy(ecs, config, image, desired_count):
    if not (image.startswith(config["repository_url"] + ":") or image.startswith(config["repository_url"] + "@sha256:")):
        raise ValueError("Image must belong to this stack's ECR repository.")
    if desired_count is None:
        current = ecs.describe_services(cluster=config["cluster"], services=[config["service"]])["services"][0]
        desired_count = max(1, current["desiredCount"])
    api_definition = register_release(ecs, config["api_task_definition"], image, config, api=True)
    migration_definition = register_release(ecs, config["migrate_task_definition"], image, config)
    run_migration(ecs, config, migration_definition)
    ecs.update_service(
        cluster=config["cluster"], service=config["service"],
        taskDefinition=api_definition, desiredCount=desired_count,
    )
    ecs.get_waiter("services_stable").wait(
        cluster=config["cluster"], services=[config["service"]],
        WaiterConfig={"Delay": 15, "MaxAttempts": 80},
    )
    service = ecs.describe_services(cluster=config["cluster"], services=[config["service"]])["services"][0]
    # A circuit-breaker rollback can also reach "stable"; verify the actual revision.
    if service["taskDefinition"] != api_definition:
        raise RuntimeError("ECS rolled back this release. Inspect the service events and task logs.")
    if service["runningCount"] < desired_count:
        raise RuntimeError("The requested number of API tasks is not running.")
    check_health(config["api_url"])
    print(f"Deployment ready: {config['api_url']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("release-config.json"))
    parser.add_argument("--image", required=True)
    parser.add_argument("--tasks", type=int, choices=range(1, 5))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    ecs = boto3.client("ecs", region_name=config["region"])
    deploy(ecs, config, args.image, args.tasks)


if __name__ == "__main__":
    main()
