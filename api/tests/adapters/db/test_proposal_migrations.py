"""Story 1.8: migration 0004 creates only `customer` and `proposal` (FR45, AD-10, AD-17)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import sql

from adapters.db.readiness import bundled_head
from tests.support import API_USER, MIGRATOR_ROLE, downgrade_migrations, run_migrations

Admin = Callable[[str], psycopg.Connection[Any]]
_NOW = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)

# domain/customer_fields.py's fixed x-fill: db columns, in schema order (C1-C15).
CUSTOMER_COLUMNS = (
    "first_name",
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
    "last_name",
    "city",
    "postcode",
)

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


def test_story_1_8_migration_creates_only_customer_and_proposal(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()

    assert {row[0] for row in tables} == {
        "alembic_version",
        "product",
        "product_rider",
        "customer",
        "proposal",
        # Story 4.9's migration 0012 (answer_overrides), Story 3.3's migration 0011
        # (proposal_feedback) and Story 4.8's migration 0017 (chat_turn_log) are also on the path
        # to the bundled head this fixture migrates to; migration 0004 itself still creates only
        # `customer` and `proposal`.
        "answer_overrides",
        "proposal_feedback",
        "chat_turn_log",
    }


def test_story_1_8_customer_has_one_column_per_x_fill_db_question(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'customer' "
            "AND column_name != 'id' ORDER BY ordinal_position"
        ).fetchall()
        date_of_birth_type = connection.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'customer' AND column_name = 'date_of_birth'"
        ).fetchone()
        primary_key = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'customer'::regclass AND contype = 'p'"
        ).fetchone()

    # migration 0015 (Story FORM-218) adds customer_number too, on the path to the bundled head
    # this fixture migrates to; it's read-only display data, never one of the x-fill: db columns.
    assert {row[0] for row in columns} == {*CUSTOMER_COLUMNS, "customer_number"}
    assert date_of_birth_type == ("date",)
    assert primary_key == ("PRIMARY KEY (id)",)


def test_story_1_8_proposal_columns_and_defaults(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal' "
            "ORDER BY ordinal_position"
        ).fetchall()
        primary_key = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'proposal'::regclass AND contype = 'p'"
        ).fetchone()
        foreign_key = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'proposal'::regclass AND contype = 'f'"
        ).fetchone()

    by_name = {row[0]: (row[1], row[2]) for row in columns}
    assert by_name == {
        "id": ("NO", "uuid"),
        "customer_id": ("YES", "uuid"),
        "owner_oid": ("NO", "text"),
        "owner_seq": ("NO", "integer"),
        "schema_version": ("NO", "integer"),
        "status": ("NO", "text"),
        "revision": ("NO", "integer"),
        "conversation_id": ("YES", "text"),
        "answers": ("NO", "jsonb"),
        "created_at": ("NO", "timestamp with time zone"),
        "updated_at": ("NO", "timestamp with time zone"),
        # Story 4.4's migration 0005 adds these two (migrated_db always runs to head).
        "lock_holder": ("YES", "text"),
        "lock_expires_at": ("YES", "timestamp with time zone"),
        # Story 4.3's migration 0006 adds this one.
        "current_turn_id": ("YES", "uuid"),
        # Story 3.2's migration 0007 adds this one.
        "submitted_at": ("YES", "timestamp with time zone"),
    }
    assert primary_key == ("PRIMARY KEY (id)",)
    assert foreign_key == ("FOREIGN KEY (customer_id) REFERENCES customer(id)",)


def test_story_1_8_owner_seq_is_unique_per_owner_oid(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        _insert_proposal(
            connection, owner_oid="another-owner"
        )  # same seq, other owner: fine

        with pytest.raises(psycopg.errors.UniqueViolation):
            _insert_proposal(connection)


def test_story_1_8_status_check_constraint_rejects_anything_but_draft_or_submitted(
    admin: Admin, migrated_db: str
) -> None:
    with (
        admin(migrated_db) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        _insert_proposal(connection, status="cancelled")


def test_story_1_8_status_check_constraint_accepts_draft_and_submitted(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        _insert_proposal(connection, owner_seq=2, status="submitted")
        count = connection.execute("SELECT count(*) FROM proposal").fetchone()

    assert count == (2,)


def test_story_1_8_answers_defaults_to_an_empty_object(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        answers = connection.execute("SELECT answers FROM proposal").fetchone()

    assert answers == ({},)


def test_story_1_8_customer_id_foreign_key_rejects_an_unknown_customer(
    admin: Admin, migrated_db: str
) -> None:
    with (
        admin(migrated_db) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        _insert_proposal(
            connection, customer_id=UUID("00000000-0000-4000-8000-000000000000")
        )


def test_story_1_8_tables_are_owned_by_the_migrator(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        rows = connection.execute(
            "SELECT relname, pg_get_userbyid(relowner), relrowsecurity, "
            "relforcerowsecurity FROM pg_class "
            "WHERE relname IN ('customer', 'proposal') ORDER BY relname"
        ).fetchall()

    # AD-17's row-level security on `proposal` arrives with migration 0009 (Story 4.3 Part B);
    # `customer` gets none (`answer_overrides`, Story 4.9, is the only other table that will).
    assert rows == [
        ("customer", MIGRATOR_ROLE, False, False),
        ("proposal", MIGRATOR_ROLE, True, True),
    ]


def test_story_1_8_api_user_can_read_and_write_proposal_and_customer(
    migrated_db: str, admin: Admin
) -> None:
    with admin(migrated_db) as connection:
        privileges = connection.execute(
            "SELECT t.name, p.privilege, has_table_privilege(%s, t.name, p.privilege) "
            "FROM unnest(ARRAY['customer', 'proposal']) AS t(name) "
            "CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) AS p(privilege)",
            (API_USER,),
        ).fetchall()

    granted = {(table, privilege) for table, privilege, has in privileges if has}
    assert granted == {
        (table, privilege)
        for table in ("customer", "proposal")
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
    }


def test_story_1_8_downgrade_to_0003_then_upgrade_leaves_no_rows(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)

    downgrade_migrations(monkeypatch, migrated_db, "0003")
    with admin(migrated_db) as connection:
        tables = connection.execute(
            "SELECT to_regclass('proposal'), to_regclass('customer')"
        ).fetchone()

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        count = connection.execute("SELECT count(*) FROM proposal").fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert tables == (None, None)
    assert count == (0,)
    assert revision == [(bundled_head(),)]


# Story 3.2: migration 0007 adds only the nullable submitted_at column (AD-10).


def test_story_3_2_existing_proposal_rows_get_a_null_submitted_at(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        submitted_at = connection.execute(
            "SELECT submitted_at FROM proposal"
        ).fetchone()

    assert submitted_at == (None,)


def test_story_3_2_a_proposal_can_store_a_submitted_at(
    admin: Admin, migrated_db: str
) -> None:
    submitted = datetime(2026, 9, 27, 0, 5, tzinfo=UTC)
    with admin(migrated_db) as connection:
        _insert_proposal(connection, status="submitted", submitted_at=submitted)
        stored = connection.execute(
            "SELECT submitted_at FROM proposal"
        ).fetchone()

    assert stored == (submitted,)


def test_story_3_2_downgrade_to_0006_then_upgrade_keeps_the_row(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)

    downgrade_migrations(monkeypatch, migrated_db, "0006")
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal' "
            "AND column_name = 'submitted_at'"
        ).fetchall()

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        # The row inserted before the downgrade survives it (only submitted_at was dropped and
        # re-added), and comes back with a null submitted_at (it predates this migration).
        submitted_at = connection.execute(
            "SELECT submitted_at FROM proposal"
        ).fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert columns == []
    assert submitted_at == (None,)
    assert revision == [(bundled_head(),)]


# Story 3.3/FORM-21: migration 0011 creates only proposal_feedback (AD-8, AD-10).


def test_story_3_3_proposal_feedback_columns_pk_fk_and_check(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal_feedback' "
            "ORDER BY ordinal_position"
        ).fetchall()
        primary_key = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'proposal_feedback'::regclass AND contype = 'p'"
        ).fetchone()
        foreign_key = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'proposal_feedback'::regclass AND contype = 'f'"
        ).fetchone()

    by_name = {row[0]: (row[1], row[2]) for row in columns}
    assert by_name == {
        "proposal_id": ("NO", "uuid"),
        "rating": ("NO", "integer"),
        "comment": ("YES", "text"),
        "given_by": ("NO", "text"),
        "at": ("NO", "timestamp with time zone"),
        # Migration 0018 (Story 7.1/FORM-237, AD-20): nullable from the start (coding-style.md
        # rule 29) -- the nightly job backfills neither.
        "category": ("YES", "text"),
        "categorised_at": ("YES", "timestamp with time zone"),
    }
    assert primary_key == ("PRIMARY KEY (proposal_id)",)
    # Migration 0016 (Story FORM-227) re-adds this FK ON DELETE CASCADE, so deleting a proposal
    # removes its proposal_feedback row in the same transaction.
    assert foreign_key == (
        "FOREIGN KEY (proposal_id) REFERENCES proposal(id) ON DELETE CASCADE",
    )


def test_story_3_3_rating_check_constraint_rejects_outside_1_to_5(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        [(proposal_id,)] = connection.execute(
            "SELECT id FROM proposal"
        ).fetchall()

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO proposal_feedback "
                "(proposal_id, rating, given_by, at) VALUES (%s, 0, 'agent', now())",
                (proposal_id,),
            )


def test_story_3_3_rating_check_constraint_accepts_1_to_5(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        [(proposal_id,)] = connection.execute(
            "SELECT id FROM proposal"
        ).fetchall()
        connection.execute(
            "INSERT INTO proposal_feedback "
            "(proposal_id, rating, comment, given_by, at) "
            "VALUES (%s, 4, 'helpful', 'synthetic-owner', now())",
            (proposal_id,),
        )
        rows = connection.execute(
            "SELECT rating, comment FROM proposal_feedback"
        ).fetchall()

    assert rows == [(4, "helpful")]


def test_story_3_3_proposal_feedback_fk_rejects_an_unknown_proposal(
    admin: Admin, migrated_db: str
) -> None:
    with (
        admin(migrated_db) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        connection.execute(
            "INSERT INTO proposal_feedback "
            "(proposal_id, rating, given_by, at) VALUES (%s, 5, 'agent', now())",
            (UUID("00000000-0000-4000-8000-000000000000"),),
        )


def test_story_3_3_api_user_can_read_and_write_proposal_feedback(
    migrated_db: str, admin: Admin
) -> None:
    """As migration 0011 left it, the api role had every privilege here (no narrowing, no RLS).
    Migration 0019 (Story 7.2/FORM-238) narrows this to SELECT/INSERT/UPDATE -- no DELETE, since
    the ON DELETE CASCADE path it would serve is unreachable from the app (test_rls_catalogue.py's
    own `test_p0_api_has_select_insert_and_update_on_proposal_feedback` is the current pin; this
    one stays as the historical record of what 0011 alone granted)."""
    with admin(migrated_db) as connection:
        privileges = connection.execute(
            "SELECT privilege, "
            "has_table_privilege(%s, 'proposal_feedback', privilege) "
            "FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) AS p(privilege)",
            (API_USER,),
        ).fetchall()

    assert {privilege for privilege, has in privileges if has} == {
        "SELECT",
        "INSERT",
        "UPDATE",
    }


def test_story_3_3_proposal_feedback_gained_row_level_security_in_migration_0019(
    admin: Admin, migrated_db: str
) -> None:
    """Migration 0011 (Story 3.3/FORM-21) left this table without row-level security: AD-17 only
    covers proposal/answer_overrides, and the REST scoped(for_owner(...)) middleware already
    guarded every write that reached it at the application level. Migration 0019 (Story 7.2/
    FORM-238) adds RLS for the first time, for the nightly job's own deliberate cross-owner need
    (its own docstring, and test_rls_feedback.py, have the details) -- this renamed test is the
    historical record of that change, not a claim this table is still unprotected."""
    with admin(migrated_db) as connection:
        row = connection.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'proposal_feedback'"
        ).fetchone()

    assert row == (True, True)


def test_story_3_3_downgrade_to_0012_then_upgrade_leaves_no_rows(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        [(proposal_id,)] = connection.execute(
            "SELECT id FROM proposal"
        ).fetchall()
        connection.execute(
            "INSERT INTO proposal_feedback "
            "(proposal_id, rating, given_by, at) VALUES (%s, 3, 'agent', now())",
            (proposal_id,),
        )

    # "0012" (Story 4.9's answer_overrides), 0011's own direct parent once re-chained onto dev's
    # head at merge time -- this downgrades only 0011 itself, not 4.9's or 5.1's migrations
    # underneath it.
    downgrade_migrations(monkeypatch, migrated_db, "0012")
    with admin(migrated_db) as connection:
        table = connection.execute(
            "SELECT to_regclass('proposal_feedback')"
        ).fetchone()

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        count = connection.execute(
            "SELECT count(*) FROM proposal_feedback"
        ).fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert table == (None,)
    assert count == (0,)
    assert revision == [(bundled_head(),)]


# Story 7.1/FORM-237: migration 0018 adds proposal_feedback.category/categorised_at (AD-20).


def test_form_237_category_defaults_to_null(admin: Admin, migrated_db: str) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        [(proposal_id,)] = connection.execute("SELECT id FROM proposal").fetchall()
        connection.execute(
            "INSERT INTO proposal_feedback "
            "(proposal_id, rating, given_by, at) VALUES (%s, 5, 'agent', now())",
            (proposal_id,),
        )
        row = connection.execute(
            "SELECT category, categorised_at FROM proposal_feedback WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()

    # No backfill (this migration's docstring): an existing or freshly inserted row starts
    # uncategorised, exactly what the nightly job's own "nothing to do" case (AD-20) checks for.
    assert row == (None, None)


@pytest.mark.parametrize("category", ["Accuracy", "Other", "No comment"])
def test_form_237_category_check_constraint_accepts_the_closed_list(
    admin: Admin, migrated_db: str, category: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        [(proposal_id,)] = connection.execute("SELECT id FROM proposal").fetchall()
        connection.execute(
            "INSERT INTO proposal_feedback "
            "(proposal_id, rating, given_by, at, category, categorised_at) "
            "VALUES (%s, 4, 'agent', now(), %s, now())",
            (proposal_id, category),
        )
        row = connection.execute(
            "SELECT category FROM proposal_feedback WHERE proposal_id = %s", (proposal_id,)
        ).fetchone()

    assert row == (category,)


def test_form_237_category_check_constraint_rejects_a_value_outside_the_closed_list(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_proposal(connection)
        [(proposal_id,)] = connection.execute("SELECT id FROM proposal").fetchall()

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO proposal_feedback "
                "(proposal_id, rating, given_by, at, category) "
                "VALUES (%s, 4, 'agent', now(), 'Not a real category')",
                (proposal_id,),
            )


def test_form_237_downgrade_to_0017_then_upgrade_restores_the_columns(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade_migrations(monkeypatch, migrated_db, "0017")
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal_feedback'"
        ).fetchall()

    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        columns_after = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'proposal_feedback'"
        ).fetchall()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert {row[0] for row in columns} == {
        "proposal_id",
        "rating",
        "comment",
        "given_by",
        "at",
    }
    assert {row[0] for row in columns_after} == {
        "proposal_id",
        "rating",
        "comment",
        "given_by",
        "at",
        "category",
        "categorised_at",
    }
    assert revision == [(bundled_head(),)]
