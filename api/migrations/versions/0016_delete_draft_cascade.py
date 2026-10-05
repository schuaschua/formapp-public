"""Delete a draft proposal: cascade its ``answer_overrides``/``proposal_feedback`` rows in the
same transaction, with a guard on ``answer_overrides`` (Story FORM-227, owner decision comment
2026-09-27, amending AD-6/Story 4.9's append-only rule for exactly this one case).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-27

Re-chained onto ``0015`` (Story FORM-218's ``customer_number``) at rebase time: ``origin/dev``'s
head moved from ``0011`` to ``0015`` while this lane was in flight (FORM-218 landed first). 0015
only adds a column/sequence/index to ``customer``; it touches neither ``proposal_feedback`` nor
``answer_overrides``, so nothing else in this migration's own logic changes -- re-verified against
the versions directory / :func:`adapters.db.readiness.bundled_head` right before the PR, in case
another lane lands a migration first still.

Three changes, all in this one migration:

1. ``GRANT DELETE ON answer_overrides TO <api principal>`` -- the same role migration 0012 already
   narrowed to ``SELECT, INSERT`` only; never ``UPDATE`` (security.md rule 31's own exception is
   "delete of the whole row once its parent is gone", never an update of one).
2. ``fk_answer_overrides_proposal`` (migration 0012) and ``fk_proposal_feedback_proposal``
   (migration 0011) are each dropped and re-added ``ON DELETE CASCADE``, so a ``DELETE FROM
   proposal`` removes every row that references it, in the same transaction, with no second
   application-level delete step.
3. A ``BEFORE DELETE FOR EACH ROW`` trigger on ``answer_overrides``, ``answer_overrides_guard_
   delete`` -- ``formapp_migrator`` (``current_user`` after its own ``SET ROLE``, the real
   migration role AD-17 always runs as) is exempt outright, and so is a genuine PostgreSQL
   superuser (``current_setting('is_superuser')``): a downgrade, or a manual fix, may still need to
   touch a row directly, and this repo's own test fixtures (``tests/conftest.py``'s ``admin``) reach
   the database as the raw superuser, never by ``SET ROLE formapp_migrator`` -- 0012's own P0 test
   proving the migrator can still update/delete a row directly (``test_p0_formapp_migrator_can_
   still_update_and_delete_answer_overrides``) exercises exactly that connection, and must keep
   passing unmodified (spec Boundaries). Every other role may delete a row only once its parent
   ``proposal`` is gone -- checked with ``EXISTS (SELECT 1 FROM proposal WHERE id = OLD.
   proposal_id)``, which is false both for a genuinely orphaned row and, crucially, for the
   cascade's own fired delete: Postgres increments the command counter after the parent row's own
   ``DELETE`` and before the ``ON DELETE CASCADE`` trigger fires the child deletes, so by the time
   this trigger's ``EXISTS`` runs, the parent is already invisible to it, in the same command (spec
   Design Notes: "the one genuinely non-obvious part", integration-tested against real Postgres in
   ``tests/adapters/db/test_rls.py``, never only reasoned about). A direct ``DELETE FROM
   answer_overrides`` with the parent still present is rejected with ``RAISE EXCEPTION``, keeping
   0012's append-only guarantee everywhere except this one case.

This trigger's own ``EXISTS`` query against ``proposal`` runs under whatever role fired the
triggering ``DELETE`` (a plain ``plpgsql`` function is ``SECURITY INVOKER`` by default, never
``DEFINER``), so it is itself subject to ``proposal``'s row-level security (migration 0009) -- the
``DELETE /api/proposals/:id`` route's own transaction must scope both ``app.proposal_id`` and
``app.owner_oid`` (spec Boundaries), not just ``owner_oid``, or this ``EXISTS`` can't see the
parent row it needs to check against.
"""

from collections.abc import Sequence

from alembic import op
from psycopg import sql

from migrations.session import api_principal

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUARD_FUNCTION = "answer_overrides_guard_delete"
_GUARD_TRIGGER = "answer_overrides_guard_delete_trigger"


def upgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)

    # 1. Append-only for UPDATE stays exactly as 0012 left it; DELETE is now allowed at the grant
    # level, gated by the trigger below (security.md rule 31's own new exception).
    op.execute(f"GRANT DELETE ON answer_overrides TO {api_role}")

    # 2. Both foreign keys cascade now, so one DELETE FROM proposal removes everything that
    # references it, in the same transaction (AC1).
    op.execute(
        "ALTER TABLE answer_overrides DROP CONSTRAINT fk_answer_overrides_proposal"
    )
    op.execute(
        "ALTER TABLE answer_overrides ADD CONSTRAINT fk_answer_overrides_proposal "
        "FOREIGN KEY (proposal_id) REFERENCES proposal (id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE proposal_feedback DROP CONSTRAINT fk_proposal_feedback_proposal"
    )
    op.execute(
        "ALTER TABLE proposal_feedback ADD CONSTRAINT fk_proposal_feedback_proposal "
        "FOREIGN KEY (proposal_id) REFERENCES proposal (id) ON DELETE CASCADE"
    )

    # 3. The guard trigger: formapp_migrator bypasses it outright; every other role may delete a
    # row only once its parent proposal is gone (or already gone) from this command's own view.
    op.execute(
        f"CREATE FUNCTION {_GUARD_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $guard$ "
        "BEGIN "
        "IF current_user = 'formapp_migrator' OR current_setting('is_superuser') = 'on' THEN "
        "RETURN OLD; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM proposal WHERE id = OLD.proposal_id) THEN "
        "RAISE EXCEPTION "
        "'answer_overrides is append-only; delete the parent proposal instead of this row directly.'; "  # noqa: E501
        "END IF; "
        "RETURN OLD; "
        "END; "
        "$guard$"
    )
    op.execute(
        f"CREATE TRIGGER {_GUARD_TRIGGER} BEFORE DELETE ON answer_overrides "
        f"FOR EACH ROW EXECUTE FUNCTION {_GUARD_FUNCTION}()"
    )


def downgrade() -> None:
    api_role = sql.Identifier(api_principal()).as_string(None)

    op.execute(f"DROP TRIGGER {_GUARD_TRIGGER} ON answer_overrides")
    op.execute(f"DROP FUNCTION {_GUARD_FUNCTION}()")

    op.execute(
        "ALTER TABLE proposal_feedback DROP CONSTRAINT fk_proposal_feedback_proposal"
    )
    op.execute(
        "ALTER TABLE proposal_feedback ADD CONSTRAINT fk_proposal_feedback_proposal "
        "FOREIGN KEY (proposal_id) REFERENCES proposal (id)"
    )
    op.execute(
        "ALTER TABLE answer_overrides DROP CONSTRAINT fk_answer_overrides_proposal"
    )
    op.execute(
        "ALTER TABLE answer_overrides ADD CONSTRAINT fk_answer_overrides_proposal "
        "FOREIGN KEY (proposal_id) REFERENCES proposal (id)"
    )

    op.execute(f"REVOKE DELETE ON answer_overrides FROM {api_role}")
