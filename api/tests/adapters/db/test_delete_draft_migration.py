"""Story FORM-227: migration 0016 -- ``answer_overrides``/``proposal_feedback`` cascade with their
parent ``proposal`` row, and the ``answer_overrides`` append-only guard trigger that makes this
safe (spec Boundaries, security.md rule 31's new exception).

The row-level-security interaction with the cascade (the genuinely non-obvious part: the
``proposal_id``-keyed policy, not the ``owner_oid``-keyed one, authorizes the cascade-fired delete)
is integration-tested against the real ``api`` role in ``test_rls.py``, next to migration 0012's
own append-only tests it amends. This file covers the migration's own shape: the grant, the two
foreign keys, and the guard trigger's admin-visible behaviour."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from adapters.db.readiness import bundled_head
from tests.support import downgrade_migrations, run_migrations

Admin = Callable[[str], psycopg.Connection[Any]]

_NOW = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)


def _insert_proposal(connection: psycopg.Connection[Any], proposal_id: Any) -> None:
    connection.execute(
        "INSERT INTO proposal "
        "(id, owner_oid, owner_seq, schema_version, status, created_at, updated_at) "
        "VALUES (%s, 'synthetic-owner', 1, 1, 'draft', %s, %s)",
        (str(proposal_id), _NOW, _NOW),
    )


def _insert_override(
    connection: psycopg.Connection[Any], override_id: Any, proposal_id: Any
) -> None:
    connection.execute(
        "INSERT INTO answer_overrides "
        "(id, proposal_id, question_id, schema_version, previous_value, previous_source, "
        "new_value, model_deployment, overridden_by, at) "
        "VALUES (%s, %s, 'G1', 1, %s, 'default', %s, 'synthetic-model', "
        "'synthetic-agent-oid', %s)",
        (str(override_id), str(proposal_id), Jsonb("No"), Jsonb("Yes"), _NOW),
    )


def _insert_feedback(connection: psycopg.Connection[Any], proposal_id: Any) -> None:
    connection.execute(
        "INSERT INTO proposal_feedback (proposal_id, rating, comment, given_by, at) "
        "VALUES (%s, 5, 'Great', 'synthetic-owner', %s)",
        (str(proposal_id), _NOW),
    )


def test_form_227_deleting_the_proposal_cascades_answer_overrides_and_feedback(
    admin: Admin, migrated_db: str
) -> None:
    proposal_id = uuid4()
    with admin(migrated_db) as connection:
        _insert_proposal(connection, proposal_id)
        _insert_override(connection, uuid4(), proposal_id)
        _insert_feedback(connection, proposal_id)

        connection.execute("DELETE FROM proposal WHERE id = %s", (str(proposal_id),))

        overrides = connection.execute(
            "SELECT count(*) FROM answer_overrides WHERE proposal_id = %s",
            (str(proposal_id),),
        ).fetchone()
        feedback = connection.execute(
            "SELECT count(*) FROM proposal_feedback WHERE proposal_id = %s",
            (str(proposal_id),),
        ).fetchone()

    assert overrides == (0,)
    assert feedback == (0,)


def test_form_227_formapp_migrator_can_still_delete_an_answer_overrides_row_directly(
    admin: Admin, migrated_db: str
) -> None:
    """The guard trigger exempts ``formapp_migrator`` outright (a downgrade, or a manual fix, may
    still need to touch a row directly) -- the admin fixture connects as a superuser, which
    bypasses grants and RLS alike, so this only proves the trigger itself doesn't block the
    migrator even while the parent proposal still exists."""
    proposal_id = uuid4()
    override_id = uuid4()
    with admin(migrated_db) as connection:
        _insert_proposal(connection, proposal_id)
        _insert_override(connection, override_id, proposal_id)

        result = connection.execute(
            "DELETE FROM answer_overrides WHERE id = %s", (str(override_id),)
        )
        assert result.rowcount == 1
        still_there = connection.execute(
            "SELECT count(*) FROM proposal WHERE id = %s", (str(proposal_id),)
        ).fetchone()

    assert still_there == (1,)  # the parent was never touched, only the override row


def test_form_227_downgrade_to_0015_then_upgrade_leaves_the_head_at_0016(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade_migrations(monkeypatch, migrated_db, "0015")
    proposal_id = uuid4()
    with admin(migrated_db) as connection:
        _insert_proposal(connection, proposal_id)
        _insert_override(connection, uuid4(), proposal_id)
    # The re-added foreign key has no ON DELETE CASCADE once downgraded: a direct delete of the
    # still-referenced parent must fail, not silently cascade.
    with (
        admin(migrated_db) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        connection.execute("DELETE FROM proposal WHERE id = %s", (str(proposal_id),))

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert revision == [(bundled_head(),)]
