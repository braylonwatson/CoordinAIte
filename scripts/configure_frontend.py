"""Point Vercel's same-origin /api proxy at the verified AWS HTTPS endpoint."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "release-config.json")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    origin = config["api_url"].rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.username:
        raise ValueError("Expected an HTTPS API origin without a path or credentials.")
    destination = ROOT / "frontend" / "vercel.json"
    document = {
        "$schema": "https://openapi.vercel.sh/vercel.json",
        "buildCommand": "REACT_APP_API_URL=/api npm run build",
        "rewrites": [{"source": "/api/:path*", "destination": origin + "/:path*"}],
        "headers": [{"source": "/api/:path*", "headers": [
            {"key": "Cache-Control", "value": "no-store"},
            {"key": "x-vercel-enable-rewrite-caching", "value": "0"},
        ]}],
    }
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing != document:
            raise RuntimeError("frontend/vercel.json already differs; merge the proxy changes explicitly.")
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print("Wrote frontend/vercel.json. Commit and push this file after the AWS health check passes.")


if __name__ == "__main__":
    main()
