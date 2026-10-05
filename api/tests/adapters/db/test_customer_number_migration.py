"""Story FORM-218: migration 0015 backfills a valid, unique customer_number for every one of
migration 0013's seeded rows, and the sequence it draws from continues from there for new
customers (spine AD-13)."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from psycopg import sql

from adapters.db.readiness import bundled_head
from domain.customer_numbers import is_valid
from tests.support import downgrade_migrations, run_migrations

Admin = Callable[[str], psycopg.Connection[Any]]


def _customer_numbers(connection: psycopg.Connection[Any]) -> list[str]:
    rows = connection.execute(
        sql.SQL("SELECT customer_number FROM customer ORDER BY id")
    ).fetchall()
    return [row[0] for row in rows]


def test_story_218_every_seeded_row_gets_a_valid_customer_number(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        numbers = _customer_numbers(connection)

    assert numbers, "expected the seed rows to have been backfilled"
    for number in numbers:
        assert number is not None
        assert is_valid(number), f"{number} is not a valid customer number"


def test_story_218_every_seeded_row_gets_a_unique_customer_number(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        numbers = _customer_numbers(connection)

    assert len(set(numbers)) == len(numbers)


def test_story_218_the_column_is_unique_at_the_database_level(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        (first_number,) = connection.execute(
            "SELECT customer_number FROM customer ORDER BY id LIMIT 1"
        ).fetchone()
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "UPDATE customer SET customer_number = %s "
                "WHERE id = (SELECT id FROM customer ORDER BY id OFFSET 1 LIMIT 1)",
                (first_number,),
            )


def test_story_218_downgrade_drops_the_column_and_sequence(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade_migrations(monkeypatch, migrated_db, "0011")
    with admin(migrated_db) as connection:
        column_exists = connection.execute(
            "SELECT to_regclass('customer_number_seq') IS NOT NULL"
        ).fetchone()[0]
        assert column_exists is False
        has_column = connection.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'customer' AND column_name = 'customer_number'"
        ).fetchone()[0]
        assert has_column == 0

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        numbers = _customer_numbers(connection)

    assert revision == [(bundled_head(),)]
    assert all(is_valid(number) for number in numbers)
