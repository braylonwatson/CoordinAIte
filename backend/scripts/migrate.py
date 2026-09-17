"""Run once per release with the RDS migration credentials, before updating ECS."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from psycopg2 import sql
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import Settings


def main():
    url = make_url(Settings.from_environment().database_url)
    arguments = url.translate_connect_args(username="user")
    arguments.update(url.query)
    # Session-level lock spans all migrations, across independently started jobs.
    with psycopg2.connect(**arguments) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '120s'")
            cursor.execute("SELECT pg_advisory_lock(714021901)")
            try:
                config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
                command.upgrade(config, "head")
                role = os.environ["APPLICATION_DATABASE_USER"]
                password = os.environ["APPLICATION_DATABASE_PASSWORD"]
                cursor.execute(
                    "SELECT rolsuper, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s", (role,)
                )
                attributes = cursor.fetchone()
                if attributes is not None and any(attributes):
                    raise RuntimeError("The application role must not have privileged role attributes.")
                if attributes is None:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                # RDS administrators have CREATEROLE, not PostgreSQL SUPERUSER.
                # New roles default to NOSUPERUSER; do not try to ALTER that flag.
                cursor.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN NOCREATEDB NOCREATEROLE PASSWORD %s")
                    .format(sql.Identifier(role)), (password,),
                )
                cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
                # Keep DDL and the Alembic revision table inaccessible to the API.
                for table in ("users", "saved_games", "game_sessions", "auth_sessions"):
                    cursor.execute(
                        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}")
                        .format(sql.Identifier(table), sql.Identifier(role))
                    )
                cursor.execute(
                    sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}")
                    .format(sql.Identifier(role))
                )
            finally:
                cursor.execute("SELECT pg_advisory_unlock(714021901)")
    print("Database migrations and application grants completed.")


if __name__ == "__main__":
    main()
