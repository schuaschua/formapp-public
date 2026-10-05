"""Row-level security on proposal (Story 4.3 Part B, spine AD-17, security.md rule 37).

Revision ID: 0009
Revises: 0007
Create Date: 2026-09-27

Enables and forces row-level security on ``proposal``, so the ``api`` request role is never exempt
(0008 is reserved for Story 3.3 and does not exist yet -- do not create it here). Three permissive
policies:

- ``proposal_migrator_all`` -- ``TO formapp_migrator``, ``USING (true) WITH CHECK (true)``: the
  migration role has no ``BYPASSRLS`` (Entra-only auth means the admin can't grant it), so it needs
  this policy of its own to keep creating and altering every object.
- ``proposal_api_by_proposal_id`` -- ``TO <api principal>``, matching ``app.proposal_id``: MCP's
  scope.
- ``proposal_api_by_owner_oid`` -- ``TO <api principal>``, matching ``app.owner_oid``: REST and
  chat's scope.

Both api policies read their setting with ``NULLIF(current_setting(..., true), '')`` (missing-or-
empty-is-null, never an error), so a transaction that never sets either one -- or reuses a pooled
session whose last transaction set and committed one of them, which resets it to ``''`` rather than
NULL -- sees zero rows instead of raising ``invalid input syntax for type uuid``. Both fields are set
with ``SET LOCAL`` by the one shared function, ``api/adapters/db/scope.py``. No policy is ``TO PUBLIC``.
Only ``proposal`` gets row-level security in this migration; ``answer_overrides`` (Story 4.9) is not
in scope here.

The api principal's role name isn't a fixed literal: [ASSUMPTION] it's read from ``DB_API_PRINCIPAL``
the same way ``DB_MIGRATION_ROLE`` already is (``migrations/session.py``'s ``api_principal()``), and
quoted with ``psycopg.sql.Identifier`` before being interpolated into the DDL string, so a role name
with punctuation (the deployed managed identity, ``id-sample-demo-sea-api``) is never string-glued
in unsafely.
"""

from collections.abc import Sequence

from alembic import op
from psycopg import sql

from migrations.session import api_principal

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIGRATOR_POLICY = "proposal_migrator_all"
_PROPOSAL_ID_POLICY = "proposal_api_by_proposal_id"
_OWNER_OID_POLICY = "proposal_api_by_owner_oid"


def upgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)
    op.execute("ALTER TABLE proposal ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE proposal FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_MIGRATOR_POLICY} ON proposal AS PERMISSIVE FOR ALL "
        "TO formapp_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {_PROPOSAL_ID_POLICY} ON proposal AS PERMISSIVE FOR ALL "
        f"TO {api_role} "
        "USING (id = NULLIF(current_setting('app.proposal_id', true), '')::uuid) "
        "WITH CHECK (id = NULLIF(current_setting('app.proposal_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY {_OWNER_OID_POLICY} ON proposal AS PERMISSIVE FOR ALL "
        f"TO {api_role} "
        "USING (owner_oid = NULLIF(current_setting('app.owner_oid', true), '')) "
        "WITH CHECK (owner_oid = NULLIF(current_setting('app.owner_oid', true), ''))"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {_OWNER_OID_POLICY} ON proposal")
    op.execute(f"DROP POLICY {_PROPOSAL_ID_POLICY} ON proposal")
    op.execute(f"DROP POLICY {_MIGRATOR_POLICY} ON proposal")
    op.execute("ALTER TABLE proposal NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE proposal DISABLE ROW LEVEL SECURITY")
