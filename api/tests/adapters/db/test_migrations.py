"""Story 1.3: the migrations run like the deploy step, as the migration role (AD-10, AD-17)."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from adapters.db.readiness import bundled_head
from migrations.session import LOCK_TIMEOUT, STATEMENT_TIMEOUT, prepare_session
from tests.support import (
    DEPLOY_PASSWORD,
    DEPLOY_USER,
    MIGRATOR_ROLE,
    run_migrations,
)

Admin = Callable[[str], psycopg.Connection[Any]]


def test_story_1_3_migrations_are_owned_by_the_migration_role(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        revisions = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        owners = dict(
            connection.execute(
                "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        )

    assert revisions == [(bundled_head(),)]
    assert set(owners) == {
        "alembic_version",
        "product",
        "product_rider",
        "customer",
        "proposal",
        "answer_overrides",
        # Story 3.3's migration 0011 (migrated_db always runs to head).
        "proposal_feedback",
        # Story 4.8's migration 0017.
        "chat_turn_log",
    }
    # No tables but ours: every table in the schema was created by a migration, as the role.
    assert set(owners.values()) == {MIGRATOR_ROLE}


def test_story_1_3_migrations_are_idempotent(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_migrations(monkeypatch, migrated_db)

    with admin(migrated_db) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall() == [(bundled_head(),)]


def test_story_1_3_migration_refuses_a_role_it_cannot_set(
    admin: Admin, fresh_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(DBAPIError, match="synthetic_missing_role"):
        run_migrations(monkeypatch, fresh_db, role="synthetic_missing_role")

    with admin(fresh_db) as connection:
        assert connection.execute(
            "SELECT to_regclass('alembic_version')"
        ).fetchone() == (None,)


@pytest.mark.parametrize("role", ["", "  "])
def test_story_1_3_migration_refuses_to_run_without_a_role(
    admin: Admin, fresh_db: str, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    with pytest.raises(RuntimeError, match="DB_MIGRATION_ROLE is not set"):
        run_migrations(monkeypatch, fresh_db, role=role)

    with admin(fresh_db) as connection:
        assert connection.execute(
            "SELECT to_regclass('alembic_version')"
        ).fetchone() == (None,)


def test_story_1_3_migration_session_has_role_and_timeouts(
    fresh_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PGUSER", DEPLOY_USER)
    monkeypatch.setenv("PGPASSWORD", DEPLOY_PASSWORD)
    with psycopg.connect(dbname=fresh_db) as connection:
        prepare_session(connection, MIGRATOR_ROLE)
        user, lock, statement = connection.execute(
            "SELECT current_user, current_setting('lock_timeout'), "
            "current_setting('statement_timeout')"
        ).fetchone() or (None, None, None)

    assert (user, lock, statement) == (MIGRATOR_ROLE, LOCK_TIMEOUT, "1min")
    assert STATEMENT_TIMEOUT == "60s"
