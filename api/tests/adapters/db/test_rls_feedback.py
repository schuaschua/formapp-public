"""Story 7.2/FORM-238 P0: migration 0019's row-level security on ``proposal_feedback``, enforced
against the real ``api`` database role (never a superuser that would bypass it, security.md rule
37) -- the same discipline ``test_rls.py`` uses for ``proposal``/``answer_overrides``.

Setup rows are written through the admin (superuser) connection, which sees and writes every row
regardless of policy -- the point here is what the ``api`` role itself can and can't do, with and
without ``app.job_scope`` set."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

pytestmark = pytest.mark.p0

Admin = Callable[[str], psycopg.Connection[Any]]
ApiConnect = Callable[[str], psycopg.Connection[Any]]


def _seed(
    admin: Admin, dbname: str, proposal_id: UUID, owner_oid: str, *, comment: str | None = None
) -> None:
    with admin(dbname) as connection:
        connection.execute(
            "INSERT INTO proposal "
            "(id, owner_oid, owner_seq, schema_version, status, created_at, updated_at) "
            "VALUES (%s, %s, 1, 1, 'draft', now(), now())",
            (str(proposal_id), owner_oid),
        )
        connection.execute(
            "INSERT INTO proposal_feedback (proposal_id, rating, comment, given_by, at) "
            "VALUES (%s, 3, %s, 'agent', now())",
            (str(proposal_id), comment),
        )


def test_p0_with_no_scope_set_api_sees_no_pending_rows(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    _seed(admin, migrated_db, uuid4(), "owner-a")

    with api_connect(migrated_db) as connection, connection.transaction():
        rows = connection.execute("SELECT proposal_id FROM proposal_feedback").fetchall()

    assert rows == []


def test_p0_job_scope_sees_every_owners_rows(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a, proposal_b = uuid4(), uuid4()
    _seed(admin, migrated_db, proposal_a, "owner-a")
    _seed(admin, migrated_db, proposal_b, "owner-b")

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.job_scope', 'true', true)")
        rows = connection.execute(
            "SELECT proposal_id FROM proposal_feedback ORDER BY proposal_id"
        ).fetchall()

    assert {row[0] for row in rows} == {proposal_a, proposal_b}


def test_p0_job_scope_allows_updating_the_category(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_id = uuid4()
    _seed(admin, migrated_db, proposal_id, "owner-a")

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.job_scope', 'true', true)")
        result = connection.execute(
            "UPDATE proposal_feedback SET category = 'Praise', categorised_at = now() "
            "WHERE proposal_id = %s",
            (str(proposal_id),),
        )
        assert result.rowcount == 1


def test_p0_without_job_scope_the_update_touches_no_rows(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_id = uuid4()
    _seed(admin, migrated_db, proposal_id, "owner-a")

    with api_connect(migrated_db) as connection, connection.transaction():
        result = connection.execute(
            "UPDATE proposal_feedback SET category = 'Praise', categorised_at = now() "
            "WHERE proposal_id = %s",
            (str(proposal_id),),
        )
        assert result.rowcount == 0

    with admin(migrated_db) as admin_connection:
        row = admin_connection.execute(
            "SELECT category FROM proposal_feedback WHERE proposal_id = %s", (str(proposal_id),)
        ).fetchone()
    assert row is not None
    assert row[0] is None


def test_p0_insert_works_without_any_scope_set(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """Preserves today's REST submit-feedback path (application-level ownership check, no RLS
    scope needed for this table's INSERT, per migration 0011's own docstring)."""
    proposal_id = uuid4()
    with admin(migrated_db) as connection:
        connection.execute(
            "INSERT INTO proposal "
            "(id, owner_oid, owner_seq, schema_version, status, created_at, updated_at) "
            "VALUES (%s, 'owner-a', 1, 1, 'draft', now(), now())",
            (str(proposal_id),),
        )

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute(
            "INSERT INTO proposal_feedback (proposal_id, rating, given_by, at) "
            "VALUES (%s, 4, 'agent', now())",
            (str(proposal_id),),
        )

    with admin(migrated_db) as admin_connection:
        row = admin_connection.execute(
            "SELECT rating FROM proposal_feedback WHERE proposal_id = %s", (str(proposal_id),)
        ).fetchone()
    assert row is not None
    assert row[0] == 4


def test_p0_api_cannot_delete_a_row_at_all(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """No DELETE grant for api (migration 0019's own docstring): the FK's ON DELETE CASCADE path
    it would otherwise serve is unreachable from the app (a submitted proposal, the only kind with
    feedback, can never be deleted)."""
    proposal_id = uuid4()
    _seed(admin, migrated_db, proposal_id, "owner-a")

    with (
        api_connect(migrated_db) as connection,
        connection.transaction(),
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "DELETE FROM proposal_feedback WHERE proposal_id = %s", (str(proposal_id),)
        )


def test_p0_job_scope_never_leaks_into_a_normal_owner_scoped_transaction(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """``app.job_scope`` is a distinct session key from ``app.owner_oid``/``app.proposal_id``
    (AD-17); setting one never sets the other."""
    proposal_id = uuid4()
    _seed(admin, migrated_db, proposal_id, "owner-a")

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.owner_oid', 'owner-a', true)")
        rows = connection.execute("SELECT proposal_id FROM proposal_feedback").fetchall()

    assert rows == []
