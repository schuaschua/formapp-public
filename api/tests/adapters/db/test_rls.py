"""Story 4.3 Part B / Story 4.9 P0: PostgreSQL's row-level security enforces AD-17 against the real
``api`` database role, never against a superuser that would bypass it (security.md rule 37), for
``proposal`` (migration 0009) and ``answer_overrides`` (migration 0012) alike.

Setup rows are written through the admin (superuser) connection, which sees and writes every row
regardless of policy -- the point here is what the ``api`` role itself can and can't do."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.p0

Admin = Callable[[str], psycopg.Connection[Any]]
ApiConnect = Callable[[str], psycopg.Connection[Any]]

_OWNER_A = "00000000-0000-4000-8000-00000000000a"
_OWNER_B = "00000000-0000-4000-8000-00000000000b"


def _seed(
    admin: Admin, dbname: str, proposal_id: UUID, owner_oid: str, owner_seq: int = 1
) -> None:
    with admin(dbname) as connection:
        connection.execute(
            "INSERT INTO proposal "
            "(id, owner_oid, owner_seq, schema_version, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, 1, 'draft', now(), now())",
            (str(proposal_id), owner_oid, owner_seq),
        )


def _seed_override(
    admin: Admin,
    dbname: str,
    override_id: UUID,
    proposal_id: UUID,
    question_id: str = "G1",
) -> None:
    """A stored ``answer_overrides`` row (Story 4.9) referencing an already-seeded ``proposal``."""
    with admin(dbname) as connection:
        connection.execute(
            "INSERT INTO answer_overrides "
            "(id, proposal_id, question_id, schema_version, previous_value, previous_source, "
            "new_value, model_deployment, overridden_by, at) "
            "VALUES (%s, %s, %s, 1, %s, 'default', %s, 'synthetic-model', "
            "'synthetic-agent-oid', now())",
            (
                str(override_id),
                str(proposal_id),
                question_id,
                Jsonb("No"),
                Jsonb("Yes"),
            ),
        )


def test_p0_a_transaction_scoped_to_one_proposal_cannot_update_another(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a, proposal_b = uuid4(), uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    _seed(admin, migrated_db, proposal_b, _OWNER_B)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute(
            "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
        )
        result = connection.execute(
            "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_b),)
        )
        assert result.rowcount == 0

    with admin(migrated_db) as admin_connection:
        row = admin_connection.execute(
            "SELECT revision FROM proposal WHERE id = %s", (str(proposal_b),)
        ).fetchone()
    assert row is not None
    assert row[0] == 0


def test_p0_a_transaction_scoped_to_one_owner_cannot_update_another_owners_proposal(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a, proposal_b = uuid4(), uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    _seed(admin, migrated_db, proposal_b, _OWNER_B)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_A,))
        result = connection.execute(
            "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_b),)
        )
        assert result.rowcount == 0

    with admin(migrated_db) as admin_connection:
        row = admin_connection.execute(
            "SELECT revision FROM proposal WHERE id = %s", (str(proposal_b),)
        ).fetchone()
    assert row is not None
    assert row[0] == 0


def test_p0_an_unscoped_transaction_sees_and_changes_zero_rows(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)

    with api_connect(migrated_db) as connection, connection.transaction():
        # No SET LOCAL at all: neither app.proposal_id nor app.owner_oid is set.
        rows = connection.execute("SELECT * FROM proposal").fetchall()
        assert rows == []
        result = connection.execute(
            "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_a),)
        )
        assert result.rowcount == 0

    with admin(migrated_db) as admin_connection:
        row = admin_connection.execute(
            "SELECT revision FROM proposal WHERE id = %s", (str(proposal_a),)
        ).fetchone()
    assert row is not None
    assert row[0] == 0


def test_p0_a_transaction_scoped_to_its_own_proposal_or_owner_can_see_and_update_it(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """The negative cases above would pass vacuously if the api role couldn't reach its own rows
    either (e.g. a missing grant): prove the matching scope still works."""
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute(
            "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
        )
        result = connection.execute(
            "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_a),)
        )
        assert result.rowcount == 1

    proposal_b = uuid4()
    _seed(admin, migrated_db, proposal_b, _OWNER_B)
    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_B,))
        result = connection.execute(
            "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_b),)
        )
        assert result.rowcount == 1


def test_p0_a_committed_set_config_on_a_pooled_connection_does_not_poison_the_next_transaction(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """Regression test: a connection pool can hand the same physical session first to an MCP
    request (scoped by ``app.proposal_id``) and later to a REST/chat request (scoped by
    ``app.owner_oid``), or vice versa. Once a transaction that ``set_config(..., true)``'d one of
    these commits, Postgres's reset value for that setting is ``''``, not NULL -- so the *other*
    policy's ``current_setting(...)::uuid`` cast must tolerate ``''`` via ``NULLIF``, or it raises
    ``invalid input syntax for type uuid: ""`` even though its own scope is satisfied."""
    proposal_a, proposal_b, proposal_c, proposal_d = uuid4(), uuid4(), uuid4(), uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A, owner_seq=1)
    _seed(admin, migrated_db, proposal_b, _OWNER_B, owner_seq=1)
    _seed(admin, migrated_db, proposal_c, _OWNER_A, owner_seq=2)
    _seed(admin, migrated_db, proposal_d, _OWNER_B, owner_seq=2)

    connection = api_connect(migrated_db)
    try:
        # 1. Proposal-scoped transaction (an MCP request), committed.
        with connection.transaction():
            connection.execute(
                "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
            )
            result = connection.execute(
                "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_a),)
            )
            assert result.rowcount == 1

        # 2. Owner-scoped transaction (a REST request) reusing the SAME connection: this is the
        # bug scenario -- app.proposal_id's reset value is now '', not NULL.
        with connection.transaction():
            connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_B,))
            result = connection.execute(
                "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_b),)
            )
            assert result.rowcount == 1

        # 3. Reverse order: owner-scoped transaction, committed, then proposal-scoped.
        with connection.transaction():
            connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_A,))
            result = connection.execute(
                "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_c),)
            )
            assert result.rowcount == 1

        with connection.transaction():
            connection.execute(
                "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_d),)
            )
            result = connection.execute(
                "UPDATE proposal SET revision = revision + 1 WHERE id = %s", (str(proposal_d),)
            )
            assert result.rowcount == 1

        # 4. Unscoped transaction after both kinds have run and committed: both settings' reset
        # values are now '' -- must see zero rows and must NOT raise.
        with connection.transaction():
            rows = connection.execute("SELECT * FROM proposal").fetchall()
            assert rows == []
    finally:
        connection.close()


# Story 4.9: answer_overrides -- the same MCP (proposal_id) and REST/chat (owner_oid, via EXISTS on
# the row's own proposal) scoping as proposal itself, plus its api role's append-only grant.


def test_p0_answer_overrides_scoped_to_one_proposal_cannot_see_anothers_rows(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a, proposal_b = uuid4(), uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    _seed(admin, migrated_db, proposal_b, _OWNER_B)
    override_a, override_b = uuid4(), uuid4()
    _seed_override(admin, migrated_db, override_a, proposal_a)
    _seed_override(admin, migrated_db, override_b, proposal_b)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute(
            "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
        )
        rows = connection.execute("SELECT id FROM answer_overrides").fetchall()
        assert [str(row[0]) for row in rows] == [str(override_a)]


def test_p0_answer_overrides_scoped_to_one_owner_cannot_see_another_owners_rows(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a, proposal_b = uuid4(), uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    _seed(admin, migrated_db, proposal_b, _OWNER_B)
    override_a, override_b = uuid4(), uuid4()
    _seed_override(admin, migrated_db, override_a, proposal_a)
    _seed_override(admin, migrated_db, override_b, proposal_b)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_A,))
        rows = connection.execute("SELECT id FROM answer_overrides").fetchall()
        assert [str(row[0]) for row in rows] == [str(override_a)]


def test_p0_an_unscoped_transaction_sees_zero_answer_overrides_rows(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    _seed_override(admin, migrated_db, uuid4(), proposal_a)

    with api_connect(migrated_db) as connection, connection.transaction():
        # No SET LOCAL at all: neither app.proposal_id nor app.owner_oid is set.
        rows = connection.execute("SELECT * FROM answer_overrides").fetchall()
        assert rows == []


def test_p0_a_transaction_scoped_to_its_own_proposal_or_owner_can_insert_and_read_it_back(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """The negative cases above would pass vacuously if the api role couldn't reach its own rows
    either (e.g. a missing grant): prove the matching scope still works, for both INSERT (the only
    write AC1 leaves the api role) and SELECT."""
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute(
            "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
        )
        connection.execute(
            "INSERT INTO answer_overrides "
            "(proposal_id, question_id, schema_version, previous_value, previous_source, "
            "new_value, model_deployment, overridden_by, at) "
            "VALUES (%s, 'G1', 1, %s, 'default', %s, 'synthetic-model', "
            "'synthetic-agent-oid', now())",
            (str(proposal_a), Jsonb("No"), Jsonb("Yes")),
        )
        rows = connection.execute(
            "SELECT question_id FROM answer_overrides WHERE proposal_id = %s",
            (str(proposal_a),),
        ).fetchall()
        assert [row[0] for row in rows] == ["G1"]

    proposal_b = uuid4()
    _seed(admin, migrated_db, proposal_b, _OWNER_B)
    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_B,))
        connection.execute(
            "INSERT INTO answer_overrides "
            "(proposal_id, question_id, schema_version, previous_value, previous_source, "
            "new_value, model_deployment, overridden_by, at) "
            "VALUES (%s, 'G1', 1, %s, 'default', %s, 'synthetic-model', "
            "'synthetic-agent-oid', now())",
            (str(proposal_b), Jsonb("No"), Jsonb("Yes")),
        )
        rows = connection.execute(
            "SELECT question_id FROM answer_overrides WHERE proposal_id = %s",
            (str(proposal_b),),
        ).fetchall()
        assert [row[0] for row in rows] == ["G1"]


def test_p0_api_cannot_update_or_delete_answer_overrides(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """AC1/security.md rule 31: ``answer_overrides`` is append-only for the ``api`` role. ``UPDATE``
    still fails on the table-level grant alone (``InsufficientPrivilege``) -- the api role is never
    granted it (Story FORM-227 leaves this exactly as it was), whether or not the row is even in
    scope. ``DELETE`` is granted as of migration 0016 (the FORM-227 cascade), but gated by
    ``answer_overrides``'s own guard trigger instead: a direct delete with the row's parent
    ``proposal`` still present is rejected with a plpgsql ``RAISE EXCEPTION`` (SQLSTATE ``P0001``,
    ``psycopg.errors.RaiseException``), never silently allowed -- scoped by ``app.proposal_id`` so
    the row is even reachable past its own RLS policies (migration 0012) for the guard trigger to
    fire on in the first place. Deleting the parent ``proposal`` instead (same scope) is the one
    case the guard lets through: the row cascades away in the same transaction (migration 0016)."""
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    override_id = uuid4()
    _seed_override(admin, migrated_db, override_id, proposal_a)

    connection = api_connect(migrated_db)
    try:
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            connection.transaction(),
        ):
            connection.execute(
                "UPDATE answer_overrides SET question_id = 'G2' WHERE id = %s",
                (str(override_id),),
            )
        with (
            pytest.raises(psycopg.errors.RaiseException),
            connection.transaction(),
        ):
            connection.execute(
                "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
            )
            connection.execute(
                "DELETE FROM answer_overrides WHERE id = %s", (str(override_id),)
            )
    finally:
        connection.close()

    with admin(migrated_db) as admin_connection:
        row = admin_connection.execute(
            "SELECT question_id FROM answer_overrides WHERE id = %s",
            (str(override_id),),
        ).fetchone()
    assert row is not None
    assert row[0] == "G1"  # untouched: neither statement above actually ran

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute(
            "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
        )
        connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_A,))
        connection.execute("DELETE FROM proposal WHERE id = %s", (str(proposal_a),))

    with admin(migrated_db) as admin_connection:
        remaining = admin_connection.execute(
            "SELECT count(*) FROM answer_overrides WHERE id = %s", (str(override_id),)
        ).fetchone()
    assert remaining == (0,)  # cascaded away with its parent, in the same transaction


def test_p0_formapp_migrator_can_still_update_and_delete_answer_overrides(
    admin: Admin, migrated_db: str
) -> None:
    """The append-only fencing in the test above is specific to the ``api`` role (AD-17): the
    owning ``formapp_migrator`` role -- the admin fixture connects as a superuser, which bypasses
    RLS and grants alike, so this only proves the grant itself isn't a blanket ``REVOKE ALL FROM
    PUBLIC`` that would also lock out a real migrator session -- can still reach every row."""
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    override_id = uuid4()
    _seed_override(admin, migrated_db, override_id, proposal_a)

    with admin(migrated_db) as connection:
        result = connection.execute(
            "UPDATE answer_overrides SET question_id = 'G2' WHERE id = %s",
            (str(override_id),),
        )
        assert result.rowcount == 1
        result = connection.execute(
            "DELETE FROM answer_overrides WHERE id = %s", (str(override_id),)
        )
        assert result.rowcount == 1


# FORM-227: deleting a draft cascades answer_overrides/proposal_feedback in the same transaction
# (migration 0016) -- but only when the api role's own RLS scope sets app.proposal_id too, not just
# app.owner_oid (spec Boundaries, spec Design Notes "the one genuinely non-obvious part"):
# SqlProposalStore.delete nests Scope(proposal_id=..., owner_oid=...) around its own transaction
# for exactly this reason.


def test_p0_deleting_the_proposal_cascades_answer_overrides_when_scoped_by_proposal_id_too(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """Mirrors ``SqlProposalStore.delete``'s own scope: both GUCs set, so the cascade-fired
    ``DELETE`` on ``answer_overrides`` is authorized by its ``proposal_id``-keyed policy regardless
    of whether the ``owner_oid``-keyed one's ``EXISTS(...)`` still sees the parent row mid-cascade."""
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    override_id = uuid4()
    _seed_override(admin, migrated_db, override_id, proposal_a)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute(
            "SELECT set_config('app.proposal_id', %s, true)", (str(proposal_a),)
        )
        connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_A,))
        result = connection.execute(
            "DELETE FROM proposal WHERE id = %s", (str(proposal_a),)
        )
        assert result.rowcount == 1

    with admin(migrated_db) as admin_connection:
        remaining = admin_connection.execute(
            "SELECT count(*) FROM answer_overrides WHERE id = %s", (str(override_id),)
        ).fetchone()
    assert remaining == (0,)


def test_p0_deleting_the_proposal_scoped_by_owner_oid_alone_still_cascades_answer_overrides(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """Superseded by migration 0016 (Story FORM-227): PostgreSQL's own foreign-key enforcement
    (the ``ON DELETE CASCADE`` this migration adds) runs the referencing-table delete as part of
    referential-integrity checking, which is not itself subject to that table's row-level security
    -- unlike the ``answer_overrides`` guard trigger's own ``EXISTS`` check against ``proposal``,
    which *is* an ordinary query and does need the row to still be visible. So scoping the delete
    transaction by ``app.owner_oid`` alone -- never setting ``app.proposal_id`` -- still lets the
    outer ``proposal`` ``DELETE`` through (its own ``owner_oid``-keyed policy) *and* still cascades
    away every referencing ``answer_overrides`` row: no orphan, this scoping alone is no longer the
    reason nothing is left behind. ``SqlProposalStore.delete`` still nests both ``proposal_id`` and
    ``owner_oid`` into its own scope regardless (spec Boundaries) -- belt and braces for the outer
    ``proposal`` row's own visibility, not because the cascade itself needs it."""
    proposal_a = uuid4()
    _seed(admin, migrated_db, proposal_a, _OWNER_A)
    override_id = uuid4()
    _seed_override(admin, migrated_db, override_id, proposal_a)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.owner_oid', %s, true)", (_OWNER_A,))
        result = connection.execute(
            "DELETE FROM proposal WHERE id = %s", (str(proposal_a),)
        )
        assert result.rowcount == 1

    with admin(migrated_db) as admin_connection:
        remaining = admin_connection.execute(
            "SELECT count(*) FROM answer_overrides WHERE id = %s", (str(override_id),)
        ).fetchone()
    assert remaining == (0,)  # cascaded away regardless -- FK enforcement bypasses RLS
