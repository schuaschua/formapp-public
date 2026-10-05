"""Test helpers: settings, and a database laid out like demo's (infra/bootstrap/README.md step 3)."""

import os
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from adapters.settings import Settings

# A known synthetic signing key (spine AD-18: tests supply their own).
TEST_SIGNING_KEY = "synthetic-signing-key-" * 2

# Roles that mirror demo's database principals (infra/bootstrap/README.md step 3).
MIGRATOR_ROLE = "formapp_migrator"
API_USER = "formapp_api_test"
DEPLOY_USER = "formapp_deploy_test"
# Synthetic local-only passwords for the throwaway test server.
API_PASSWORD = "synthetic-api-password"  # noqa: S105 -- test server only
DEPLOY_PASSWORD = "synthetic-deploy-password"  # noqa: S105 -- test server only

API_ROOT = Path(__file__).resolve().parent.parent
# Story 1.7: the released form schemas, their lint and its fixtures (repo root, next to api/).
FORM_SCHEMA_DIR = API_ROOT.parent / "form-schema"

# Story 1.6: request headers that sign a test in as synthetic agent A or B (test mode only, AD-18).
AS_AGENT_A = {"X-Formapp-Test-Principal": "agent-a"}
AS_AGENT_B = {"X-Formapp-Test-Principal": "agent-b"}


def make_settings(**overrides: Any) -> Settings:
    """Settings for a local deployment, test mode on (AD-18); each test overrides what it checks."""
    values: dict[str, Any] = {
        "formapp_deployment": "local",
        "database_host": "127.0.0.1",
        "database_name": "formapp_test",
        "database_user": API_USER,
        "database_password": API_PASSWORD,
        "database_sslmode": "disable",
        "db_migration_role": MIGRATOR_ROLE,
        "turn_token_signing_key": TEST_SIGNING_KEY,
        "formapp_test_mode": True,
    }
    values.update(overrides)
    return Settings(**values)


def admin_available() -> bool:
    return bool(os.environ.get("PGHOST"))


def admin_connect(dbname: str = "postgres") -> psycopg.Connection[Any]:
    # Everything but the database name comes from the PG* variables.
    return psycopg.connect(dbname=dbname, autocommit=True)


def _create_roles(connection: psycopg.Connection[Any]) -> None:
    for role, options in (
        (MIGRATOR_ROLE, sql.SQL("NOLOGIN")),
        (API_USER, sql.SQL("LOGIN PASSWORD {}").format(sql.Literal(API_PASSWORD))),
        (
            DEPLOY_USER,
            sql.SQL("LOGIN PASSWORD {}").format(sql.Literal(DEPLOY_PASSWORD)),
        ),
    ):
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
        ).fetchone()
        if not exists:
            connection.execute(
                sql.SQL("CREATE ROLE {} {}").format(sql.Identifier(role), options)
            )
    connection.execute(
        sql.SQL("REVOKE {} FROM {}").format(
            sql.Identifier(MIGRATOR_ROLE), sql.Identifier(API_USER)
        )
    )
    # As in demo: the pipeline identity may SET ROLE to the migrator but inherits nothing.
    connection.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
            sql.Identifier(MIGRATOR_ROLE), sql.Identifier(DEPLOY_USER)
        )
    )


def create_database(dbname: str) -> None:
    """(Re)create a database laid out like demo's formapp database."""
    with admin_connect() as connection:
        _create_roles(connection)
        name = sql.Identifier(dbname)
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name)
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                name, sql.Identifier(MIGRATOR_ROLE)
            )
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                name, sql.Identifier(API_USER)
            )
        )
    with admin_connect(dbname) as connection:
        migrator, api = sql.Identifier(MIGRATOR_ROLE), sql.Identifier(API_USER)
        for statement in (
            "ALTER SCHEMA public OWNER TO {migrator}",
            "REVOKE ALL ON SCHEMA public FROM PUBLIC",
            "GRANT USAGE ON SCHEMA public TO {api}",
            (
                "ALTER DEFAULT PRIVILEGES FOR ROLE {migrator} IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {api}"
            ),
            (
                "ALTER DEFAULT PRIVILEGES FOR ROLE {migrator} IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {api}"
            ),
        ):
            connection.execute(sql.SQL(statement).format(migrator=migrator, api=api))


def drop_database(dbname: str) -> None:
    with admin_connect() as connection:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(dbname)
            )
        )


def set_api_migrator_membership(granted: bool) -> None:
    """Grant or revoke the migration role to the test api user (server-wide)."""
    statement = "GRANT {} TO {}" if granted else "REVOKE {} FROM {}"
    with admin_connect() as connection:
        connection.execute(
            sql.SQL(statement).format(
                sql.Identifier(MIGRATOR_ROLE), sql.Identifier(API_USER)
            )
        )


def run_migrations(
    monkeypatch: pytest.MonkeyPatch,
    dbname: str,
    role: str = MIGRATOR_ROLE,
    revision: str = "head",
    api_principal: str = API_USER,
) -> None:
    """Run `alembic upgrade` as the deploy step does: PG* variables and SET ROLE.

    ``api_principal`` (Story 4.3 Part B, AD-17) is the role migration 0009's row-level security
    policies grant to the ``api`` request role; it defaults to the same test role the fixtures use
    for the api database user, so the live policies match what the tests actually connect as.
    """
    _alembic(
        monkeypatch,
        dbname,
        role,
        lambda config: command.upgrade(config, revision),
        api_principal,
    )


def downgrade_migrations(
    monkeypatch: pytest.MonkeyPatch,
    dbname: str,
    revision: str,
    api_principal: str = API_USER,
) -> None:
    """Run `alembic downgrade` the same way, as the migration role."""
    _alembic(
        monkeypatch,
        dbname,
        MIGRATOR_ROLE,
        lambda config: command.downgrade(config, revision),
        api_principal,
    )


def _alembic(
    monkeypatch: pytest.MonkeyPatch,
    dbname: str,
    role: str,
    run: Callable[[Config], None],
    api_principal: str = API_USER,
) -> None:
    with monkeypatch.context() as patch:
        patch.setenv("PGUSER", DEPLOY_USER)
        patch.setenv("PGPASSWORD", DEPLOY_PASSWORD)
        patch.setenv("PGDATABASE", dbname)
        patch.setenv("DB_MIGRATION_ROLE", role)
        patch.setenv("DB_API_PRINCIPAL", api_principal)
        run(Config(str(API_ROOT / "alembic.ini")))


# Story 2.1: the seeded catalogue, spelled out from the content draft's Products and Riders tables
# so a test notices any change. Product rows: code, name, type, covers_dependents, policy_terms,
# sum_assured_min, sum_assured_max, default_sum_assured, default_term, min_age, max_age,
# baseline_monthly.
def _terms(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in pairs]


D = Decimal
EXPECTED_PRODUCTS: list[tuple[Any, ...]] = [
    ("CFH", "CareFirst Health", "health", True,
     _terms(("1_yr_renewable", "1 yr, renewable")),
     None, None, None, "1_yr_renewable", 18, 65, D("45.00")),
    ("ELH", "Essentials Life & Health", "life_health", False,
     _terms(("10_yrs", "10 yrs"), ("20_yrs", "20 yrs")),
     D("100000.00"), D("300000.00"), D("150000.00"), "10_yrs", 18, 60, D("100.00")),
    ("FSH", "FamilyShield Life & Health", "life_health", True,
     _terms(("20_yrs", "20 yrs"), ("30_yrs", "30 yrs")),
     D("200000.00"), D("600000.00"), D("300000.00"), "20_yrs", 18, 55, D("160.00")),
    ("LT20", "SecureLife Term", "life", True,
     _terms(("10_yrs", "10 yrs"), ("20_yrs", "20 yrs"), ("30_yrs", "30 yrs")),
     D("100000.00"), D("500000.00"), D("200000.00"), "20_yrs", 18, 60, D("60.00")),
    ("LWL", "Legacy Whole Life", "life", True,
     _terms(("whole_of_life", "Whole of life")),
     D("250000.00"), D("1000000.00"), D("500000.00"), "whole_of_life", 18, 70, D("260.00")),
]  # fmt: skip
# Rider rows: code, product_code, name, baseline_monthly.
EXPECTED_RIDERS: list[tuple[str, str, str, Decimal]] = [
    ("R01", "LT20", "Critical illness", D("20.00")),
    ("R02", "LT20", "Accidental death", D("8.00")),
    ("R03", "LT20", "Waiver of premium", D("5.00")),
    ("R04", "FSH", "Hospital cash", D("15.00")),
    ("R05", "FSH", "Critical illness", D("25.00")),
    ("R06", "FSH", "Child cover", D("12.00")),
    ("R07", "FSH", "Maternity & newborn", D("30.00")),
    ("R08", "ELH", "Hospital cash", D("12.00")),
    ("R09", "ELH", "Critical illness", D("20.00")),
    ("R10", "CFH", "Dental & optical", D("10.00")),
    ("R11", "CFH", "Outpatient", D("15.00")),
    ("R12", "LWL", "Waiver of premium", D("10.00")),
    ("R13", "LWL", "Accidental death", D("12.00")),
]


# Story 1.4: the web app's security headers, spelled out so a test notices any change.
EXPECTED_CSP = {
    "default-src": "'self'",
    "script-src": "'self'",
    "style-src": "'self'",
    "img-src": "'self' data:",
    "font-src": "'self'",
    "connect-src": "'self'",
    "form-action": "'self'",
    "base-uri": "'self'",
    "object-src": "'none'",
    "frame-ancestors": "'none'",
}
EXPECTED_PERMISSIONS = {
    "accelerometer",
    "camera",
    "geolocation",
    "gyroscope",
    "magnetometer",
    "payment",
    "usb",
}


def parse_csp(header: str) -> dict[str, str]:
    """Directive name -> value; a directive with no value (e.g. upgrade-insecure-requests) maps to ""."""
    directives: dict[str, str] = {}
    for part in header.split(";"):
        name, _, value = part.strip().partition(" ")
        if name:
            directives[name.lower()] = " ".join(value.split())
    return directives


def parse_permissions_policy(header: str) -> dict[str, str]:
    """Feature -> allowlist, e.g. {"camera": "()"}."""
    features: dict[str, str] = {}
    for part in header.split(","):
        name, _, allowlist = part.strip().partition("=")
        if name:
            features[name] = allowlist
    return features


def assert_web_security_headers(headers: Any) -> None:
    """The CSP has exactly the expected directives; every listed feature is denied and the microphone
    is allowed to this origin only (Story 6.2)."""
    assert parse_csp(headers["content-security-policy"]) == EXPECTED_CSP
    assert "unsafe" not in headers["content-security-policy"]
    assert parse_permissions_policy(headers["permissions-policy"]) == {
        **dict.fromkeys(EXPECTED_PERMISSIONS, "()"),
        "microphone": "(self)",  # Story 6.2: this origin only, for hold-to-talk
    }
