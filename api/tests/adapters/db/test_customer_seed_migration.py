"""Story 5.1: migration 0010 seeds ~10 synthetic customers, every C1-C15 column filled (NFR7,
AD-13)."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from psycopg import sql

from adapters.db.readiness import bundled_head
from tests.support import downgrade_migrations, run_migrations

Admin = Callable[[str], psycopg.Connection[Any]]

# domain/customer_fields.py's fixed x-fill: db columns (C1-C15); `id` isn't one of them.
CUSTOMER_COLUMNS = (
    "first_name",
    "last_name",
    "date_of_birth",
    "sex_at_birth",
    "country_of_origin",
    "country_of_residence",
    "id_number",
    "email",
    "mobile",
    "street_address",
    "occupation",
    "marital_status",
    "income_range",
    "city",
    "postcode",
)
_ALL_COLUMNS = ("id", *CUSTOMER_COLUMNS)


def _select_all(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    query = sql.SQL("SELECT {} FROM customer").format(
        sql.SQL(", ").join(map(sql.Identifier, _ALL_COLUMNS))
    )
    rows = connection.execute(query).fetchall()
    return [dict(zip(_ALL_COLUMNS, row, strict=True)) for row in rows]


def test_story_5_1_migration_seeds_about_ten_customers(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        rows = _select_all(connection)

    assert 8 <= len(rows) <= 12


def test_story_5_1_every_seeded_row_fills_every_c1_c15_column(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        rows = _select_all(connection)

    assert rows, "expected the seed migration to insert rows"
    for row in rows:
        for column in CUSTOMER_COLUMNS:
            assert row[column] is not None, f"{column} is null on row {row['id']}"


def test_story_5_1_seed_includes_two_similar_name_rows(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        rows = _select_all(connection)

    last_names = [row["last_name"] for row in rows]
    # Two rows share the surname "Wei Ming"/"Wei Min" (one letter apart), same first name "Tan".
    similar = [row for row in rows if row["first_name"] == "Tan"]

    assert len(similar) == 2
    assert last_names.count("Wei Ming") == 1
    assert last_names.count("Wei Min") == 1


def test_story_5_1_seed_includes_the_demo_script_customer(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        rows = _select_all(connection)

    ally = [
        row
        for row in rows
        if row["first_name"] == "Ally" and row["last_name"] == "Macbeal"
    ]

    assert len(ally) == 1
    assert ally[0]["date_of_birth"].isoformat() == "1994-11-20"


def test_story_5_1_downgrade_removes_exactly_the_seeded_rows(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin(migrated_db) as connection:
        before = connection.execute("SELECT count(*) FROM customer").fetchone()

    downgrade_migrations(monkeypatch, migrated_db, "0009")
    with admin(migrated_db) as connection:
        after_downgrade = connection.execute("SELECT count(*) FROM customer").fetchone()

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        after_upgrade = connection.execute("SELECT count(*) FROM customer").fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert before[0] >= 8
    assert after_downgrade == (0,)
    assert after_upgrade == before
    assert revision == [(bundled_head(),)]
