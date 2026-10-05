"""Shared fixtures.

Unit tests need nothing. Database tests need a PostgreSQL server reached through the libpq variables
(PGHOST, PGPORT, PGUSER, PGPASSWORD) as a superuser; CI sets them for its PostgreSQL 18 service
container. Without them the database tests are skipped locally, and fail in CI.
"""

import os
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from adapters.settings import Settings
from tests.support import (
    API_PASSWORD,
    API_USER,
    admin_available,
    admin_connect,
    create_database,
    drop_database,
    make_settings,
    run_migrations,
    set_api_migrator_membership,
)

Admin = Callable[[str], psycopg.Connection[Any]]


@pytest.fixture(scope="session")
def admin() -> Callable[[str], psycopg.Connection[Any]]:
    if not admin_available():
        if os.environ.get("CI"):
            pytest.fail("CI must provide PostgreSQL through PGHOST and friends.")
        pytest.skip(
            "No PostgreSQL (set PGHOST, PGUSER, PGPASSWORD to run database tests)."
        )
    return admin_connect


@pytest.fixture
def fresh_db(admin: Callable[[str], psycopg.Connection[Any]]) -> Iterator[str]:
    """A new database laid out like demo's, unique to this test and dropped afterwards."""
    dbname = f"formapp_test_{uuid4().hex[:12]}"
    create_database(dbname)
    try:
        yield dbname
    finally:
        drop_database(dbname)


@pytest.fixture
def migrated_db(fresh_db: str, monkeypatch: pytest.MonkeyPatch) -> str:
    run_migrations(monkeypatch, fresh_db)
    return fresh_db


@pytest.fixture
def api_is_migrator(admin: Callable[[str], psycopg.Connection[Any]]) -> Iterator[None]:
    """Grant the migration role to the test api user, and always take it back."""
    set_api_migrator_membership(granted=True)
    try:
        yield
    finally:
        set_api_migrator_membership(granted=False)


@pytest.fixture
def db_settings(admin: Callable[[str], psycopg.Connection[Any]]) -> Settings:
    """Settings that sign in as the test api user on the admin's server."""
    return make_settings(
        database_host=os.environ["PGHOST"],
        database_port=int(os.environ.get("PGPORT", "5432")),
    )


@pytest.fixture
def api_connect(admin: Admin) -> Callable[[str], psycopg.Connection[Any]]:
    """A raw connection signed in as the test api role (never the admin/migrator) -- Story 4.3
    Part B's row-level security is enforced against this role, never against a superuser that
    would bypass it (AD-17)."""

    def connect(dbname: str) -> psycopg.Connection[Any]:
        return psycopg.connect(
            host=os.environ["PGHOST"],
            port=int(os.environ.get("PGPORT", "5432")),
            dbname=dbname,
            user=API_USER,
            password=API_PASSWORD,
        )

    return connect
