from scripts.deploy_aws import configure_api_container


def test_release_task_definition_adds_owner_and_support_settings_without_dropping_existing_values():
    container = {
        "name": "api",
        "environment": [
            {"name": "APP_ENV", "value": "production"},
            {"name": "REDIS_URL", "value": "rediss://cache.example:6379/0"},
        ],
        "secrets": [{"name": "JWT_SECRET_KEY", "valueFrom": "secret:jwt_secret_key::"}],
    }

    configure_api_container(container, {
        "application_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:app",
        "owner_emails": ["owner@example.com", "ops@example.com"],
        "support_email": "support@coordinaite.net",
        "smtp_username": "support@coordinaite.net",
    })

    environment = {item["name"]: item["value"] for item in container["environment"]}
    secrets = {item["name"]: item["valueFrom"] for item in container["secrets"]}
    assert environment["OWNER_EMAILS"] == "owner@example.com,ops@example.com"
    assert environment["SUPPORT_EMAIL"] == "support@coordinaite.net"
    assert environment["SMTP_USERNAME"] == "support@coordinaite.net"
    assert environment["REDIS_URL"] == "rediss://cache.example:6379/0"
    assert secrets["JWT_SECRET_KEY"] == "secret:jwt_secret_key::"
    assert secrets["SMTP_PASSWORD"].endswith(":smtp_password::")


def test_release_task_definition_has_a_safe_owner_default_for_legacy_release_config():
    container = {"name": "api", "environment": [], "secrets": []}

    configure_api_container(container, {
        "application_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:app",
    })

    environment = {item["name"]: item["value"] for item in container["environment"]}
    assert environment["OWNER_EMAILS"] == "braylon5watson@gmail.com"
