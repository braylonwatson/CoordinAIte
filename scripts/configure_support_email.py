"""Securely save the Google Workspace SMTP app password to AWS Secrets Manager."""

import argparse
import getpass
import json
import warnings
from pathlib import Path

import boto3


ROOT = Path(__file__).resolve().parents[1]


def hidden_input(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt).strip().replace(" ", "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "release-config.json")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    secret_id = config.get("application_secret_arn")
    if not secret_id:
        raise SystemExit("release-config.json must contain application_secret_arn.")

    password = hidden_input("Google Workspace app password for support@coordinaite.net: ")
    if not password:
        raise SystemExit("No app password entered; no changes made.")

    client = boto3.client("secretsmanager", region_name=args.region)
    current = client.get_secret_value(SecretId=secret_id)
    values = json.loads(current["SecretString"])
    values["smtp_password"] = password
    client.put_secret_value(SecretId=secret_id, SecretString=json.dumps(values))
    print("SMTP app password saved to Secrets Manager. The secret value was not printed.")


if __name__ == "__main__":
    main()
