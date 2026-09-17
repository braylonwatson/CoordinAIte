from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import Settings, database_url_from_environment
from app.factory import create_app
from tests.conftest import CSRF_HEADERS, TEST_JWT_SECRET


def test_ecs_database_secret_round_trips_special_characters():
    password = "p@ss:/?#[]%with space"
    url = make_url(database_url_from_environment({
        "DATABASE_HOST": "db.internal",
        "DATABASE_USER": "coordinaite_app",
        "DATABASE_PASSWORD": password,
        "DATABASE_NAME": "coordinaite",
        "DATABASE_SSLMODE": "verify-full",
        "DATABASE_SSLROOTCERT": "/app/certs/rds-bundle.pem",
        "DATABASE_URL": "postgresql://stale-render-host/old",
    }))
    assert url.password == password
    assert url.host == "db.internal"
    assert url.query["sslmode"] == "verify-full"


def test_proxy_cookie_is_sent_and_deleted_at_the_browser_path(model_bundle):
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret_key=TEST_JWT_SECRET,
        auth_cookie_path="/api/auth",
        auth_cookie_secure=True,
    )
    # The browser sees /api/auth; the reverse proxy strips /api for FastAPI.
    application = create_app(settings=settings, model_bundle=model_bundle, create_tables=True)
    with TestClient(application, base_url="https://app.example.com", headers=CSRF_HEADERS) as client:
        response = client.post("/signup", json={
            "username": "Coach", "email": "proxy@example.com", "password": "strong-pass",
        })
        cookie = response.headers["set-cookie"]
        assert "Path=/api/auth" in cookie and "HttpOnly" in cookie and "Secure" in cookie
        token = response.cookies["coordinaite_refresh"]
        refresh = client.post("/auth/refresh", headers={"Cookie": f"coordinaite_refresh={token}"})
        assert refresh.status_code == 200
        current_cookie = refresh.cookies["coordinaite_refresh"]
        logout = client.post("/auth/logout", headers={"Cookie": f"coordinaite_refresh={current_cookie}"})
        assert logout.status_code == 204
        assert "Path=/api/auth" in logout.headers["set-cookie"]
        assert "Max-Age=0" in logout.headers["set-cookie"]
        assert client.post("/auth/refresh", headers={"Cookie": f"coordinaite_refresh={current_cookie}"}).status_code == 401
