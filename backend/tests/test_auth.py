from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AuthSession, utc_now
from app.factory import create_app
from tests.conftest import CSRF_HEADERS, TEST_JWT_SECRET, register


def test_login_issues_verified_identity_and_http_only_refresh_cookie(client, app):
    user = register(client)
    assert client.get("/me").json()["user_id"] == user["user_id"]
    result = client.post("/login", json={"email": " COACH@example.com ", "password": "strong-pass"})
    assert result.status_code == 200
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/auth" in cookie and "SameSite=lax" in cookie
    assert result.headers["cache-control"] == "no-store"
    assert "refresh_token" not in result.json()
    with app.state.session_factory() as db:
        for session in db.scalars(select(AuthSession)):
            assert len(session.refresh_token_hash) == 64
            assert session.refresh_token_hash not in cookie


@pytest.mark.parametrize("email,password", [("coach@example.com", "wrong"), ("missing@example.com", "strong-pass")])
def test_invalid_login_has_same_error(client, email, password):
    register(client)
    response = client.post("/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.parametrize("change", ["expired", "signature", "audience", "issuer", "type", "missing_exp", "subject"])
def test_invalid_access_tokens_rejected(client, change):
    data = register(client)
    payload = jwt.decode(data["access_token"], TEST_JWT_SECRET, algorithms=["HS256"], audience="coordinaite-api")
    key = TEST_JWT_SECRET
    if change == "expired":
        payload["exp"] = int((utc_now() - timedelta(seconds=1)).timestamp())
    elif change == "signature":
        key = "different-signing-key-with-at-least-32-bytes"
    elif change == "audience":
        payload["aud"] = "another-app"
    elif change == "issuer":
        payload["iss"] = "another-app"
    elif change == "type":
        payload["type"] = "refresh"
    elif change == "subject":
        payload["sub"] = str(data["user_id"] + 1)
    else:
        del payload["exp"]
    forged = jwt.encode(payload, key, algorithm="HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_refresh_rotates_and_rejects_replay_and_logout_revokes_access(client):
    original = register(client)
    old_cookie = client.cookies.get("coordinaite_refresh")
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert old_cookie != client.cookies.get("coordinaite_refresh")
    assert client.post("/auth/refresh", headers={"Cookie": f"coordinaite_refresh={old_cookie}"}).status_code == 401
    assert client.get("/me").status_code == 200
    response = client.post("/auth/logout")
    assert response.status_code == 204
    assert not client.cookies.get("coordinaite_refresh")
    assert client.get("/me", headers={"Authorization": f"Bearer {original['access_token']}"}).status_code == 401
    assert client.get("/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"}).status_code == 401
    assert client.post("/auth/refresh").status_code == 401
    assert client.post("/auth/logout").status_code == 204


def test_refresh_cookie_alone_cannot_authenticate_regular_api_requests(client):
    register(client)
    del client.headers["Authorization"]
    assert client.get("/me").status_code == 401
    assert client.get("/games").status_code == 401
    assert client.post("/auth/refresh").status_code == 200


def test_expired_session_cannot_refresh_or_use_valid_access_token(client, app):
    register(client)
    with app.state.session_factory() as db:
        session = db.scalar(select(AuthSession))
        session.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert client.post("/auth/refresh").status_code == 401
    assert client.get("/me").status_code == 401


def test_cookie_mutations_require_csrf_header_and_trusted_origin(client):
    register(client)
    assert client.post("/auth/refresh", headers={"Origin": "https://attacker.example"}).status_code == 403
    del client.headers["X-CSRF-Protection"]
    assert client.post("/auth/refresh").status_code == 403
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/login", json={"email": "coach@example.com", "password": "strong-pass"}).status_code == 403
    assert client.post("/auth/refresh", headers={**CSRF_HEADERS, "Origin": "http://localhost:3000"}).status_code == 200


def test_auth_sessions_work_and_revoke_across_instances(tmp_path, model_bundle):
    settings = Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'auth.db'}", jwt_secret_key=TEST_JWT_SECRET)
    first_app = create_app(settings, model_bundle, create_tables=True)
    second_app = create_app(settings, model_bundle)
    with TestClient(first_app, headers=CSRF_HEADERS) as first, TestClient(second_app, headers=CSRF_HEADERS) as second:
        data = register(first)
        second.headers["Authorization"] = f"Bearer {data['access_token']}"
        assert second.get("/me").status_code == 200
        refreshed = second.post("/auth/refresh", headers={"Cookie": f"coordinaite_refresh={first.cookies.get('coordinaite_refresh')}"})
        assert refreshed.status_code == 200
        assert second.post("/auth/logout").status_code == 204
        assert first.get("/me").status_code == 401


def test_missing_signing_secret_fails_startup(model_bundle):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        create_app(Settings(database_url="sqlite+pysqlite:///:memory:"), model_bundle)
