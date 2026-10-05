"""Story 1.3: /readyz is 200 only at the bundled Alembic head, reachable, and without the
migration role (AD-10, AD-17). Database tests run against PostgreSQL (CI: a PostgreSQL 18 service)."""

import logging
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from adapters.db.readiness import bundled_head
from adapters.rest.app import create_app
from adapters.settings import Settings
from tests.support import API_PASSWORD, API_USER, MIGRATOR_ROLE, make_settings

SYNTHETIC_PASSWORD = "synthetic-password-must-not-log"  # noqa: S105 -- checked it never logs
Admin = Callable[[str], psycopg.Connection[Any]]


def _client(settings: Settings, dbname: str, **overrides: Any) -> TestClient:
    return TestClient(
        create_app(settings.model_copy(update={"database_name": dbname, **overrides}))
    )


@pytest.fixture
def client(db_settings: Settings, migrated_db: str) -> Iterator[TestClient]:
    with _client(db_settings, migrated_db) as test_client:
        yield test_client


def test_story_3_3_bundled_head_is_the_proposal_feedback_migration() -> None:
    # Chain: 0009 -> 0013 (Story 5.1 seed-customers) -> 0012 (Story 4.9 answer_overrides) -> 0011
    # (Story 3.3/FORM-21) -> 0015 (Story FORM-218 customer_number) -> 0016 (Story FORM-227, delete
    # a draft proposal, re-chained onto dev's head at merge time) -> 0017 (Story 4.8, chat_turn_log
    # throttle counter) -> 0018 (Story 7.1/FORM-237, proposal_feedback category/categorised_at) ->
    # 0019 (Story 7.2/FORM-238, proposal_feedback job-scope row-level security) -> 0020 (Story
    # 7.3/FORM-239, proposal job-scope submitted-only row-level security); this pins whatever the
    # current bundled head actually is, so the next migration to land updates this same line rather
    # than leaving it silently stale.
    assert bundled_head() == "0020"


def test_story_1_3_readyz_200_at_the_bundled_head(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_story_1_3_readyz_503_on_schema_revision_mismatch(
    client: TestClient, admin: Admin, migrated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    with admin(migrated_db) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'ffff'")

    with caplog.at_level(logging.WARNING):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert f"does not match the bundled head {bundled_head()}" in caplog.text


def test_story_1_3_readyz_503_before_any_migration(
    fresh_db: str, db_settings: Settings
) -> None:
    with _client(db_settings, fresh_db) as client:
        assert client.get("/readyz").status_code == 503


def test_story_1_3_readyz_503_when_api_is_a_migration_role_member(
    client: TestClient, api_is_migrator: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert "AD-17 violation" in caplog.text


def test_story_1_3_readyz_503_when_the_migration_role_does_not_exist(
    migrated_db: str, db_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        _client(
            db_settings, migrated_db, db_migration_role="synthetic_missing_role"
        ) as client,
        caplog.at_level(logging.ERROR),
    ):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert "synthetic_missing_role does not exist" in caplog.text


def test_story_1_3_readyz_503_logs_the_sqlstate_of_a_database_error(
    client: TestClient,
    admin: Admin,
    migrated_db: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with admin(migrated_db) as connection:
        connection.execute(
            sql.SQL("REVOKE SELECT ON alembic_version FROM {}").format(
                sql.Identifier(API_USER)
            )
        )

    with caplog.at_level(logging.WARNING):
        response = client.get("/readyz")

    assert response.status_code == 503
    # 42501: insufficient_privilege, logged as a database error, not as unreachable.
    assert "database error (ProgrammingError, SQLSTATE 42501)" in caplog.text
    assert "unreachable" not in caplog.text


def test_story_1_3_api_cannot_set_role_to_the_migrator(
    migrated_db: str, db_settings: Settings
) -> None:
    with (
        psycopg.connect(
            host=db_settings.database_host,
            port=db_settings.database_port,
            dbname=migrated_db,
            user=API_USER,
            password=API_PASSWORD,
        ) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(MIGRATOR_ROLE)))


def test_story_1_3_readyz_503_when_database_unreachable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Nothing listens on port 1; no database server is needed for this test.
    settings = make_settings(
        database_host="127.0.0.1",
        database_port=1,
        database_password=SYNTHETIC_PASSWORD,
    )

    with TestClient(create_app(settings)) as client, caplog.at_level(logging.WARNING):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert "database unreachable" in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert SYNTHETIC_PASSWORD not in caplog.text
    assert API_USER not in caplog.text
