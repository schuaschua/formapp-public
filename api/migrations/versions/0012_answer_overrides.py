"""``answer_overrides``: the append-only human-answer-edit audit log (Story 4.9, spine AD-17,
security.md rules 31/37, EXPERIENCE.md line 229).

Revision ID: 0012
Revises: 0013
Create Date: 2026-09-27

Re-chained onto 0013 (Story 5.1's seed-customers migration) at merge time, per the FORM-30 brief;
this migration's own number (0012) predates 0013's numerically but sits after it in the chain --
Alembic orders by ``down_revision``, not by the numeric filename prefix.

Creates the table and, in the same migration (AD-17: "``answer_overrides`` gets its policies in the
migration that creates it"), enables and forces row-level security with the same three-policy shape
migration 0009 gives ``proposal``, renamed for this table:

- ``answer_overrides_migrator_all`` -- ``TO formapp_migrator``, ``USING (true) WITH CHECK (true)``:
  the migration role's own un-fenced policy, same reason as 0009's.
- ``answer_overrides_api_by_proposal_id`` -- ``TO <api principal>``, matching ``app.proposal_id``:
  MCP's scope.
- ``answer_overrides_api_by_owner_oid`` -- ``TO <api principal>``, via ``EXISTS`` on the row's own
  proposal's ``owner_oid`` (this table has no ``owner_oid`` column of its own): REST and chat's
  scope.

Both api policies use ``NULLIF(current_setting(..., true), '')`` before the cast/comparison, never
a bare one, for the same pooled-connection reason 0009's docstring explains.

Append-only for the ``api`` role (AC1, security.md rule 31): a freshly created table would
otherwise inherit ``SELECT, INSERT, UPDATE, DELETE`` on itself for the api role from the bootstrap's
``ALTER DEFAULT PRIVILEGES FOR ROLE formapp_migrator ...`` (``infra/bootstrap/README.md`` step 3,
mirrored by ``tests.support.create_database``), since migrations run ``SET ROLE formapp_migrator``.
Right after ``CREATE TABLE``, this migration explicitly revokes that and grants back only
``SELECT, INSERT`` -- no infra change or manual step needed. ``formapp_migrator``, as the table's
owning role, keeps ``UPDATE``/``DELETE`` (needed for a downgrade or a fix), consistent with how
AD-17 treats the migrator as the one un-fenced role throughout; only the ``api`` role is fenced off
from ever updating or deleting a row here.

The api principal's role name is resolved the same way migration 0009 resolves it:
``migrations.session.api_principal()``, quoted with ``psycopg.sql.Identifier`` before being
interpolated into the DDL string.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from psycopg import sql
from sqlalchemy.dialects import postgresql

from migrations.session import api_principal

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TEXT = sa.Text()
GEN_UUID = sa.text("gen_random_uuid()")

_MIGRATOR_POLICY = "answer_overrides_migrator_all"
_PROPOSAL_ID_POLICY = "answer_overrides_api_by_proposal_id"
_OWNER_OID_POLICY = "answer_overrides_api_by_owner_oid"


def upgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)

    op.create_table(
        "answer_overrides",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "proposal_id",
            UUID,
            sa.ForeignKey("proposal.id", name="fk_answer_overrides_proposal"),
            nullable=False,
        ),
        sa.Column("question_id", TEXT, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("previous_value", postgresql.JSONB, nullable=True),
        sa.Column("previous_source", TEXT, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
        sa.Column("model_deployment", TEXT, nullable=False),
        sa.Column("overridden_by", TEXT, nullable=False),
        sa.Column("at", sa.TIMESTAMP(timezone=True), nullable=False),
    )

    # AC1/security.md rule 31: narrow the api role's default-privilege grant (SELECT, INSERT,
    # UPDATE, DELETE, inherited the instant this table was created) down to SELECT, INSERT only --
    # right after CREATE TABLE, before anything else.
    op.execute(f"REVOKE ALL ON answer_overrides FROM {api_role}")
    op.execute(f"GRANT SELECT, INSERT ON answer_overrides TO {api_role}")

    op.execute("ALTER TABLE answer_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE answer_overrides FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_MIGRATOR_POLICY} ON answer_overrides AS PERMISSIVE FOR ALL "
        "TO formapp_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {_PROPOSAL_ID_POLICY} ON answer_overrides AS PERMISSIVE FOR ALL "
        f"TO {api_role} "
        "USING (proposal_id = NULLIF(current_setting('app.proposal_id', true), '')::uuid) "
        "WITH CHECK (proposal_id = NULLIF(current_setting('app.proposal_id', true), '')::uuid)"
    )
    op.execute(
        # S608 (SQL injection via string building) is a false positive here: _OWNER_OID_POLICY is a
        # module constant, api_role is quoted with psycopg.sql.Identifier above, and the embedded
        # SELECT is DDL for the policy's own EXISTS clause -- never a query built from caller input.
        f"CREATE POLICY {_OWNER_OID_POLICY} ON answer_overrides AS PERMISSIVE FOR ALL "  # noqa: S608
        f"TO {api_role} "
        "USING (EXISTS (SELECT 1 FROM proposal p WHERE p.id = answer_overrides.proposal_id "
        "AND p.owner_oid = NULLIF(current_setting('app.owner_oid', true), ''))) "
        "WITH CHECK (EXISTS (SELECT 1 FROM proposal p WHERE p.id = answer_overrides.proposal_id "
        "AND p.owner_oid = NULLIF(current_setting('app.owner_oid', true), '')))"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {_OWNER_OID_POLICY} ON answer_overrides")
    op.execute(f"DROP POLICY {_PROPOSAL_ID_POLICY} ON answer_overrides")
    op.execute(f"DROP POLICY {_MIGRATOR_POLICY} ON answer_overrides")
    op.drop_table("answer_overrides")
