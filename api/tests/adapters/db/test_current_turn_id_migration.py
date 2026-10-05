"""Story 4.3: migration 0006 adds only the nullable `current_turn_id` column to `proposal` (AD-4)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from adapters.db.readiness import bundled_head
from tests.support import downgrade_migrations, run_migrations

Admin = Callable[[str], psycopg.Connection[Any]]
_NOW = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)

_GOOD_PROPOSAL = {
    "owner_oid": "synthetic-owner",
    "owner_seq": 1,
    "schema_version": 1,
    "status": "draft",
    "created_at": _NOW,
    "updated_at": _NOW,
}


def _insert_proposal(connection: psycopg.Connection[Any], **changes: Any) -> None:
    row = {**_GOOD_PROPOSAL, **changes}
    connection.execute(
        sql.SQL("INSERT INTO proposal ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, row)),
            sql.SQL(", ").join(map(sql.Placeholder, row)),
        ),
        row,
    )


def test_story_4_3_migration_adds_only_the_current_turn_id_column(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal' "
            "AND column_name = 'current_turn_id'"
        ).fetchall()

    assert columns == [("current_turn_id", "YES", "uuid")]


def test_story_4_3_existing_proposal_rows_get_a_null_turn(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        turn = connection.execute(
            "SELECT current_turn_id FROM proposal"
        ).fetchone()

    assert turn == (None,)


def test_story_4_3_a_proposal_can_store_a_current_turn_id(
    admin: Admin, migrated_db: str
) -> None:
    turn_id = uuid4()
    with admin(migrated_db) as connection:
        _insert_proposal(connection, current_turn_id=str(turn_id))
        stored = connection.execute(
            "SELECT current_turn_id FROM proposal"
        ).fetchone()

    assert stored == (turn_id,)


def test_story_4_3_downgrade_to_0005_then_upgrade_leaves_no_rows(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)

    downgrade_migrations(monkeypatch, migrated_db, "0005")
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal' "
            "AND column_name = 'current_turn_id'"
        ).fetchall()

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        # The row inserted before the downgrade survives it (only the one column was dropped and
        # re-added), and comes back with a null turn (Story 1.8's row predates this migration).
        turn = connection.execute("SELECT current_turn_id FROM proposal").fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert columns == []
    assert turn == (None,)
    assert revision == [(bundled_head(),)]
