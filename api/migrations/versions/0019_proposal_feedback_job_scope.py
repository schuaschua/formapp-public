"""proposal_feedback: a deliberate, least-privilege cross-owner path for the nightly feedback job
(Story 7.2/FORM-238, spine AD-17, AD-18, AD-20).

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-28

``proposal_feedback`` has never had row-level security: migration 0011's own docstring says so
("AD-17 only covers proposal/answer_overrides"; the existing REST ``scoped(for_owner(...))``
middleware already guards every write that reaches this table at the application level). The
nightly job (Story 7.1/FORM-237, AD-20) runs as the same ``api`` role REST and MCP use, but needs to
read and update every owner's NULL-category rows, not just one -- something AD-17's own
``app.proposal_id``/``app.owner_oid`` scopes can never grant, by design.

This migration adds RLS to the table for the first time, but with a *different* policy shape than
AD-17's owner_oid/proposal_id pattern, so it does not put ``proposal_feedback`` "under [AD-17's]
policies" (the architecture spine's own phrase for what would require amending that AD) -- it is a
narrower, table-local scheme for one job's one need, gated by a session flag (``app.job_scope``)
only ``jobs.feedback`` ever sets (``adapters.db.scope.for_job``), never REST or MCP. This is
deliberately not a ``SECURITY DEFINER`` function: AD-17 already says "no ... SECURITY DEFINER
function reads them" for the two tables it binds, and the same caution applies here -- a plain
policy gated by a session-local flag is auditable the same way every other RLS policy in this
schema is, and needs no elevated-privilege function to review.

Four policies, ``FORCE``d like every other RLS table in this schema (PostgreSQL's ``CREATE POLICY``
only ever takes one command per ``FOR`` clause -- no comma list -- so the job-scope path is two
policies, not one):

- ``proposal_feedback_migrator_all`` -- ``TO formapp_migrator``, ``USING (true) WITH CHECK (true)``:
  the migration role's own un-fenced policy, same reason as 0009's and 0012's.
- ``proposal_feedback_api_insert`` -- ``FOR INSERT TO <api principal> WITH CHECK (true)``: preserves
  today's unconditional REST submit-feedback insert unchanged (ownership is already checked at the
  application level before this insert runs, per 0011's own docstring). INSERT needs no companion
  SELECT visibility (there is no existing row to see), unlike UPDATE/DELETE below.
- ``proposal_feedback_api_job_scope_select`` / ``proposal_feedback_api_job_scope_update`` -- each
  ``TO <api principal>``, gated by ``current_setting('app.job_scope', true) = 'true'``: the new,
  deliberate path. Nothing else grants the api role SELECT on this table any more -- narrower than
  today's status quo (today, with no RLS at all, any api-scoped connection could already SELECT
  every row; this closes that). PostgreSQL requires a matching SELECT (or ALL) policy to identify
  the rows an UPDATE or DELETE targets in the first place, in addition to that command's own policy
  -- the select and update policies share the same condition so a job-scoped connection can do both.

No DELETE policy or grant for ``api``: ``fk_proposal_feedback_proposal`` is ``ON DELETE CASCADE``,
but ``proposal_feedback`` rows only ever exist on a *submitted* proposal (Story 3.3), and the REST
delete route rejects deleting a submitted proposal before it ever reaches the database (Story
FORM-227's ``test_form_227_delete_rejects_a_submitted_proposal``) -- so that cascade path is
unreachable from the application today. Only ``formapp_migrator`` (its own un-fenced policy, and
table ownership) can delete a row here, same as before this migration for every other write this
table never exposed to ``api``.

The api role's grant is also narrowed here, the same way migration 0012 narrows it for
``answer_overrides`` (security.md rule 31): ``REVOKE ALL`` right after enabling RLS, then
``GRANT SELECT, INSERT, UPDATE`` back explicitly (unlike ``answer_overrides``, this table's job path
genuinely needs ``UPDATE``, gated by the policy above, not by withholding the grant).

The api principal's role name is resolved the same way migrations 0009/0012 resolve it:
``migrations.session.api_principal()``, quoted with ``psycopg.sql.Identifier``.
"""

from collections.abc import Sequence

from alembic import op
from psycopg import sql

from migrations.session import api_principal

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIGRATOR_POLICY = "proposal_feedback_migrator_all"
_INSERT_POLICY = "proposal_feedback_api_insert"
_JOB_SCOPE_SELECT_POLICY = "proposal_feedback_api_job_scope_select"
_JOB_SCOPE_UPDATE_POLICY = "proposal_feedback_api_job_scope_update"
_JOB_SCOPE_CONDITION = "current_setting('app.job_scope', true) = 'true'"


def upgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)

    # security.md rule 31: narrow the api role's inherited default-privilege grant down to exactly
    # what it uses -- SELECT/UPDATE only ever succeed under the job-scope policies below.
    op.execute(f"REVOKE ALL ON proposal_feedback FROM {api_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON proposal_feedback TO {api_role}")

    op.execute("ALTER TABLE proposal_feedback ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE proposal_feedback FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_MIGRATOR_POLICY} ON proposal_feedback AS PERMISSIVE FOR ALL "
        "TO formapp_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {_INSERT_POLICY} ON proposal_feedback AS PERMISSIVE FOR INSERT "
        f"TO {api_role} WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {_JOB_SCOPE_SELECT_POLICY} ON proposal_feedback AS PERMISSIVE "
        f"FOR SELECT TO {api_role} USING ({_JOB_SCOPE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {_JOB_SCOPE_UPDATE_POLICY} ON proposal_feedback AS PERMISSIVE "
        f"FOR UPDATE TO {api_role} "
        f"USING ({_JOB_SCOPE_CONDITION}) WITH CHECK ({_JOB_SCOPE_CONDITION})"
    )


def downgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)

    op.execute(f"DROP POLICY {_JOB_SCOPE_UPDATE_POLICY} ON proposal_feedback")
    op.execute(f"DROP POLICY {_JOB_SCOPE_SELECT_POLICY} ON proposal_feedback")
    op.execute(f"DROP POLICY {_INSERT_POLICY} ON proposal_feedback")
    op.execute(f"DROP POLICY {_MIGRATOR_POLICY} ON proposal_feedback")
    op.execute("ALTER TABLE proposal_feedback NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE proposal_feedback DISABLE ROW LEVEL SECURITY")

    op.execute(f"REVOKE ALL ON proposal_feedback FROM {api_role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON proposal_feedback TO {api_role}"
    )
