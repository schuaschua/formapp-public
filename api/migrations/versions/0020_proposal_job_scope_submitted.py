"""proposal: a narrow, submitted-only read path for the nightly feedback job's snapshot export
(Story 7.3/FORM-239, spine AD-17, AD-18, AD-20).

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-28

Migration 0019 gave the nightly job (``jobs.feedback``, ``adapters.db.scope.for_job``) a
deliberate, least-privilege cross-owner path over ``proposal_feedback`` so it can categorise every
owner's pending rows. Story 7.3's snapshot export needs a second field from ``proposal`` itself for
each exported row -- ``submitted_at``, the product code (``answers->>'P1'``) and ``schema_version``
-- which the job's existing ``app.job_scope`` setting cannot reach: migration 0009's two ``proposal``
policies only ever match one proposal (``app.proposal_id``, MCP's scope) or one owner
(``app.owner_oid``, REST/chat's scope), by design (AD-17's own stated limit), and the job sets
neither.

This migration adds one more permissive policy to ``proposal``, gated by the same ``app.job_scope``
session flag 0019 introduced (never a new session key, and never REST or MCP, which never set it) --
narrower than 0019's own job-scope policies in two ways: **SELECT only** (the export never writes
``proposal``, so no UPDATE/INSERT policy is added, and the table's existing grants are left alone --
0009 never narrowed them, so ``api`` already has SELECT from the bootstrap's default privileges; RLS
alone is the gate), and **submitted proposals only** (``status = 'submitted'``, AD-20's own "for
submitted proposals only" rule enforced in the database, not just in the job's SQL), so a job-scoped
connection can never see a draft's answers even by accident. Still not a ``SECURITY DEFINER``
function, the same reasoning 0019's own docstring gives.

No grant changes: unlike 0019 (which narrowed ``proposal_feedback``'s grant because that table had
none before), ``proposal`` already carries the bootstrap's default SELECT/INSERT/UPDATE/DELETE grant
to ``api`` from migration 0009 onward, and this migration doesn't touch it -- only the new policy
decides what a job-scoped SELECT can actually see.

The api principal's role name is resolved the same way 0009/0012/0019 resolve it:
``migrations.session.api_principal()``, quoted with ``psycopg.sql.Identifier``.
"""

from collections.abc import Sequence

from alembic import op
from psycopg import sql

from migrations.session import api_principal

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_SCOPE_SELECT_POLICY = "proposal_api_job_scope_select_submitted"
_JOB_SCOPE_CONDITION = "current_setting('app.job_scope', true) = 'true' AND status = 'submitted'"


def upgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)
    op.execute(
        f"CREATE POLICY {_JOB_SCOPE_SELECT_POLICY} ON proposal AS PERMISSIVE "
        f"FOR SELECT TO {api_role} USING ({_JOB_SCOPE_CONDITION})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {_JOB_SCOPE_SELECT_POLICY} ON proposal")
