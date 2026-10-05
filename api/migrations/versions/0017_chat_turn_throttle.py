"""``chat_turn_log``: the per-``oid`` chat-turn throttle counter (Story 4.8, spine AD-9, AD-17).

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-28

Each insurance agent (``oid``) may start at most 3 chat turns in any rolling 10 seconds, across
every proposal and every replica (AD-9); ``api/domain/throttle.py`` counts rows in this table
within the window, from the injectable ``Clock`` (AD-18), never SQL ``now()``. One row per allowed
turn start -- ``oid`` and ``started_at`` -- with no other columns; a refused (throttled) request
never inserts one (Story 4.8, AC "refused requests do not count").

Row-level security, enabled and forced in this same migration (AD-17: "gets its policies in the
migration that creates it"), with the ``_api_by_owner_oid``-only shape migration 0009 gives
``proposal`` -- no ``proposal_id`` policy, since no MCP tool ever reads or writes this table
(spec Boundaries):

- ``chat_turn_log_migrator_all`` -- ``TO formapp_migrator``, ``USING (true) WITH CHECK (true)``,
  same reason as every other table under AD-17.
- ``chat_turn_log_api_by_owner_oid`` -- ``TO <api principal>``, matching ``app.owner_oid`` (the
  signed-in agent's own ``oid`` -- REST and chat's scope, AD-17), against this table's own ``oid``
  column directly (no ``EXISTS`` join needed, unlike ``answer_overrides``, since ``oid`` already
  *is* the row's owner).

Read/write-only for the api role, same shape as migration 0012's ``answer_overrides`` (security.md
rule 31): a fresh table would otherwise inherit ``SELECT, INSERT, UPDATE, DELETE`` from the
bootstrap's ``ALTER DEFAULT PRIVILEGES``, so this migration revokes that immediately after
``CREATE TABLE`` and grants back only ``SELECT, INSERT`` -- the throttle check only ever reads the
window and inserts one row; it never updates or deletes one.

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

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")

_TABLE = "chat_turn_log"
_INDEX = "ix_chat_turn_log_oid_started_at"
_MIGRATOR_POLICY = "chat_turn_log_migrator_all"
_OWNER_OID_POLICY = "chat_turn_log_api_by_owner_oid"


def upgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)

    op.create_table(
        _TABLE,
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("oid", sa.Text(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    # The throttle's own window query filters by (oid, started_at); this index is what keeps it
    # cheap as the table grows.
    op.create_index(_INDEX, _TABLE, ["oid", "started_at"])

    # security.md rule 31: narrow the api role's default-privilege grant (SELECT, INSERT, UPDATE,
    # DELETE, inherited the instant this table was created) down to SELECT, INSERT only.
    op.execute(f"REVOKE ALL ON {_TABLE} FROM {api_role}")
    op.execute(f"GRANT SELECT, INSERT ON {_TABLE} TO {api_role}")

    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_MIGRATOR_POLICY} ON {_TABLE} AS PERMISSIVE FOR ALL "
        "TO formapp_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {_OWNER_OID_POLICY} ON {_TABLE} AS PERMISSIVE FOR ALL "
        f"TO {api_role} "
        "USING (oid = NULLIF(current_setting('app.owner_oid', true), '')) "
        "WITH CHECK (oid = NULLIF(current_setting('app.owner_oid', true), ''))"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {_OWNER_OID_POLICY} ON {_TABLE}")
    op.execute(f"DROP POLICY {_MIGRATOR_POLICY} ON {_TABLE}")
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
