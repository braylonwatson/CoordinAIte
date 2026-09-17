"""One-time AWS setup using your local AWS CLI/SSO credentials. Never prints secrets."""
import argparse
import json
import secrets
import subprocess
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parents[1]


def state_bucket(region):
    session = boto3.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    bucket = f"coordinaite-tfstate-{account}-{region}"
    s3 = session.client("s3")
    try:
        s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        arguments = {"Bucket": bucket}
        if region != "us-east-1":
            arguments["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**arguments)
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
    })
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}],
    })
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "RequireTLS", "Effect": "Deny", "Principal": "*",
            "Action": "s3:*",
            "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }],
    }))
    destination = ROOT / "infra" / "aws" / "backend.hcl"
    destination.write_text(
        f'bucket = "{bucket}"\nkey = "production/terraform.tfstate"\n'
        f'region = "{region}"\nencrypt = true\nuse_lockfile = true\n',
        encoding="utf-8",
    )
    print(f"State bucket ready: {bucket}. Wrote infra/aws/backend.hcl.")


def export_config():
    result = subprocess.run(
        ["terraform", "-chdir=infra/aws", "output", "-json", "release_config"],
        cwd=ROOT, capture_output=True, check=True, text=True,
    )
    config = json.loads(result.stdout)
    (ROOT / "release-config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print("Wrote non-secret release-config.json.")


def initialize_secret(config):
    client = boto3.client("secretsmanager", region_name=config["region"])
    secret_id = config["application_secret_arn"]
    metadata = client.describe_secret(SecretId=secret_id)
    if any("AWSCURRENT" in stages for stages in metadata.get("VersionIdsToStages", {}).values()):
        print("Application secret already initialized; existing values preserved.")
        return
    client.put_secret_value(SecretId=secret_id, SecretString=json.dumps({
        "database_password": secrets.token_urlsafe(48),
        "jwt_secret_key": secrets.token_urlsafe(48),
        "stripe_secret_key": "",
        "stripe_price_id_tier2": "",
        "stripe_webhook_secret": "",
    }))
    print("Initialized database and JWT credentials in Secrets Manager. Stripe settings are empty.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["state", "export", "secrets"])
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--config", type=Path, default=ROOT / "release-config.json")
    args = parser.parse_args()
    if args.action == "state":
        state_bucket(args.region)
    elif args.action == "export":
        export_config()
    else:
        initialize_secret(json.loads(args.config.read_text(encoding="utf-8-sig")))


if __name__ == "__main__":
    main()
