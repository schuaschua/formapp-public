"""Story 7.3/FORM-239: migration 0020 adds one job-scope, submitted-only SELECT policy to
``proposal`` (spine AD-17, AD-20) and downgrades it cleanly back to migration 0019's own three
policies."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from adapters.db.readiness import bundled_head
from tests.support import downgrade_migrations, run_migrations

Admin = Callable[[str], psycopg.Connection[Any]]


def _policy_names(connection: psycopg.Connection[Any]) -> set[str]:
    rows = connection.execute(
        "SELECT policyname FROM pg_policies "
        "WHERE schemaname = 'public' AND tablename = 'proposal'"
    ).fetchall()
    return {row[0] for row in rows}


def test_form_239_head_adds_the_job_scope_submitted_policy(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        policies = _policy_names(connection)

    assert policies == {
        "proposal_migrator_all",
        "proposal_api_by_proposal_id",
        "proposal_api_by_owner_oid",
        "proposal_api_job_scope_select_submitted",
    }


def test_form_239_downgrade_drops_only_the_new_policy(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade_migrations(monkeypatch, migrated_db, "0019")

    with admin(migrated_db) as connection:
        policies = _policy_names(connection)

    assert policies == {
        "proposal_migrator_all",
        "proposal_api_by_proposal_id",
        "proposal_api_by_owner_oid",
    }

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        policies = _policy_names(connection)

    assert revision == [(bundled_head(),)]
    assert "proposal_api_job_scope_select_submitted" in policies
