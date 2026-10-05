"""Story 4.4: migration 0005 adds only the two nullable lock columns to `proposal` (AD-16)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

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


def test_story_4_4_migration_adds_only_the_two_lock_columns(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal' "
            "AND column_name IN ('lock_holder', 'lock_expires_at') "
            "ORDER BY column_name"
        ).fetchall()

    assert columns == [
        ("lock_expires_at", "YES", "timestamp with time zone"),
        ("lock_holder", "YES", "text"),
    ]


def test_story_4_4_existing_proposal_rows_get_a_null_lock(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        lock = connection.execute(
            "SELECT lock_holder, lock_expires_at FROM proposal"
        ).fetchone()

    assert lock == (None, None)


def test_story_4_4_a_proposal_can_store_a_lock_holder_and_expiry(
    admin: Admin, migrated_db: str
) -> None:
    expires = datetime(2026, 9, 27, 0, 1, tzinfo=UTC)
    with admin(migrated_db) as connection:
        _insert_proposal(
            connection, lock_holder="synthetic-session-a", lock_expires_at=expires
        )
        lock = connection.execute(
            "SELECT lock_holder, lock_expires_at FROM proposal"
        ).fetchone()

    assert lock == ("synthetic-session-a", expires)


def test_story_4_4_downgrade_to_0004_then_upgrade_leaves_no_rows(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)

    downgrade_migrations(monkeypatch, migrated_db, "0004")
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal' "
            "AND column_name IN ('lock_holder', 'lock_expires_at')"
        ).fetchall()

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        # The row inserted before the downgrade survives it (only the two columns were dropped
        # and re-added), and comes back with a null lock (Story 1.8's row predates this migration).
        lock = connection.execute(
            "SELECT lock_holder, lock_expires_at FROM proposal"
        ).fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert columns == []
    assert lock == (None, None)
    assert revision == [(bundled_head(),)]
