"""Story 7.3/FORM-239 P0: migration 0020's job-scope, submitted-only SELECT policy on ``proposal``,
enforced against the real ``api`` database role (never a superuser that would bypass it, security.md
rule 37) -- the same discipline ``test_rls_feedback.py`` uses for ``proposal_feedback``'s own
job-scope policies.

Setup rows are written through the admin (superuser) connection, which sees and writes every row
regardless of policy -- the point here is what the ``api`` role itself can and can't do, with and
without ``app.job_scope`` set, and with a draft vs. a submitted proposal."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

pytestmark = pytest.mark.p0

Admin = Callable[[str], psycopg.Connection[Any]]
ApiConnect = Callable[[str], psycopg.Connection[Any]]


def _seed(
    admin: Admin,
    dbname: str,
    proposal_id: UUID,
    owner_oid: str,
    *,
    status: str,
    submitted: bool,
) -> None:
    with admin(dbname) as connection:
        connection.execute(
            "INSERT INTO proposal "
            "(id, owner_oid, owner_seq, schema_version, status, created_at, updated_at, "
            "submitted_at) "
            "VALUES (%s, %s, 1, 1, %s, now(), now(), CASE WHEN %s THEN now() ELSE NULL END)",
            (str(proposal_id), owner_oid, status, submitted),
        )


def test_p0_with_no_scope_set_api_sees_no_submitted_proposals(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_id = uuid4()
    _seed(admin, migrated_db, proposal_id, "owner-a", status="submitted", submitted=True)

    with api_connect(migrated_db) as connection, connection.transaction():
        rows = connection.execute("SELECT id FROM proposal").fetchall()

    assert rows == []


def test_p0_job_scope_sees_every_owners_submitted_proposal(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_a, proposal_b = uuid4(), uuid4()
    _seed(admin, migrated_db, proposal_a, "owner-a", status="submitted", submitted=True)
    _seed(admin, migrated_db, proposal_b, "owner-b", status="submitted", submitted=True)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.job_scope', 'true', true)")
        rows = connection.execute("SELECT id FROM proposal ORDER BY id").fetchall()

    assert {row[0] for row in rows} == {proposal_a, proposal_b}


def test_p0_job_scope_never_sees_a_draft_proposal(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    """AC: "for submitted proposals only" (AD-20, FR65), enforced in the database too."""
    proposal_id = uuid4()
    _seed(admin, migrated_db, proposal_id, "owner-a", status="draft", submitted=False)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.job_scope', 'true', true)")
        rows = connection.execute("SELECT id FROM proposal").fetchall()

    assert rows == []


def test_p0_job_scope_never_leaks_into_a_normal_owner_scoped_transaction(
    admin: Admin, migrated_db: str, api_connect: ApiConnect
) -> None:
    proposal_id = uuid4()
    _seed(admin, migrated_db, proposal_id, "owner-a", status="submitted", submitted=True)

    with api_connect(migrated_db) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.owner_oid', 'owner-b', true)")
        rows = connection.execute("SELECT id FROM proposal").fetchall()

    assert rows == []
