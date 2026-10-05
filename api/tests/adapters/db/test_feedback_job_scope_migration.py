"""Story 7.2/FORM-238: migration 0019 adds row-level security to ``proposal_feedback`` for the
first time (spine AD-17, AD-20) and downgrades it cleanly back to migration 0018's plain,
RLS-free table."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from adapters.db.readiness import bundled_head
from tests.support import downgrade_migrations, run_migrations

Admin = Callable[[str], psycopg.Connection[Any]]


def _rls_state(connection: psycopg.Connection[Any]) -> tuple[bool, bool]:
    row = connection.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = 'proposal_feedback' AND relnamespace = 'public'::regnamespace"
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def _policy_count(connection: psycopg.Connection[Any]) -> int:
    (count,) = connection.execute(
        "SELECT count(*) FROM pg_policies "
        "WHERE schemaname = 'public' AND tablename = 'proposal_feedback'"
    ).fetchone()
    return count


def test_form_238_head_has_rls_enabled_and_forced(admin: Admin, migrated_db: str) -> None:
    with admin(migrated_db) as connection:
        enabled, forced = _rls_state(connection)
        policies = _policy_count(connection)

    assert (enabled, forced) == (True, True)
    assert policies == 4


def test_form_238_downgrade_drops_rls_and_narrows_back_to_no_policies(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade_migrations(monkeypatch, migrated_db, "0018")

    with admin(migrated_db) as connection:
        enabled, forced = _rls_state(connection)
        policies = _policy_count(connection)

    assert (enabled, forced) == (False, False)
    assert policies == 0

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        enabled, forced = _rls_state(connection)

    assert revision == [(bundled_head(),)]
    assert (enabled, forced) == (True, True)
