"""Real Postgres release/locking checks. CI provides an isolated disposable server."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2 import sql
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.factory import create_app
from tests.conftest import CSRF_HEADERS, TEST_JWT_SECRET, create_game


@pytest.fixture
def postgres_application_url():
    source = os.getenv("TEST_POSTGRES_URL")
    if not source:
        pytest.skip("TEST_POSTGRES_URL not set; run CI or the disposable Postgres container.")
    base = make_url(source)
    if base.database != "coordinaite_test":
        pytest.fail("TEST_POSTGRES_URL must point to the disposable coordinaite_test database.")
    suffix = uuid4().hex
    database, role, migration_role = f"test_{suffix}", f"app_{suffix}", f"migrate_{suffix}"
    password = "only-in-disposable-ci"
    admin = psycopg2.connect(**base.translate_connect_args(username="user"))
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            # Exercise the migration with RDS-like privileges, not a superuser.
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN CREATEDB CREATEROLE PASSWORD %s")
                .format(sql.Identifier(migration_role)), (password,),
            )
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}")
                .format(sql.Identifier(database), sql.Identifier(migration_role))
            )
        url = base.set(database=database, username=migration_role, password=password)
        environment = {
            **os.environ,
            "DATABASE_URL": url.render_as_string(hide_password=False),
            "APPLICATION_DATABASE_USER": role,
            "APPLICATION_DATABASE_PASSWORD": password,
        }
        # Never inherit component credentials from the caller's AWS environment.
        for key in ("DATABASE_HOST", "DATABASE_USER", "DATABASE_PASSWORD", "DATABASE_NAME"):
            environment.pop(key, None)
        for _ in range(2):  # First bootstrap and an idempotent subsequent release.
            result = subprocess.run(
                [sys.executable, "scripts/migrate.py"],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                capture_output=True, text=True, timeout=60,
            )
            assert result.returncode == 0, result.stderr
        yield url.set(username=role, password=password).render_as_string(hide_password=False)
    finally:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
            cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(migration_role)))
        admin.close()


def test_runtime_role_can_write_data_but_cannot_change_schema(postgres_application_url):
    url = make_url(postgres_application_url)
    with psycopg2.connect(**url.translate_connect_args(username="user")) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user")
            assert cursor.fetchone() == (False, False, False)
            cursor.execute("SELECT count(*) FROM users")
            assert cursor.fetchone()[0] == 0
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE forbidden_schema_change (id int)")


def test_two_workers_serialize_game_mutations_and_refresh_replay(postgres_application_url, model_bundle):
    settings = Settings(database_url=postgres_application_url, jwt_secret_key=TEST_JWT_SECRET)
    apps = [create_app(settings=settings, model_bundle=model_bundle) for _ in range(2)]
    try:
        with TestClient(apps[0], headers=CSRF_HEADERS) as client:
            game_id = create_game(client, "KC", "BUF")
            authorization = client.headers["Authorization"]
            cookie = client.cookies["coordinaite_refresh"]

        def new_drive(index):
            with TestClient(apps[index % 2], headers={**CSRF_HEADERS, "Authorization": authorization}) as client:
                response = client.post("/new-drive", json={"game_id": game_id})
                assert response.status_code == 200, response.text
                return response.json()["drive_number"]

        with ThreadPoolExecutor(max_workers=4) as executor:
            numbers = list(executor.map(new_drive, range(12)))
        assert sorted(numbers) == list(range(2, 14))

        def refresh(index):
            with TestClient(apps[index], headers=CSRF_HEADERS) as client:
                return client.post("/auth/refresh", headers={"Cookie": f"coordinaite_refresh={cookie}"}).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(refresh, range(2)))
        assert sorted(statuses) == [200, 401]
    finally:
        for app in apps:
            app.state.engine.dispose()
