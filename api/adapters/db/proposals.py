"""The stored proposal, read and written for the domain's ``ProposalStore`` port (Story 1.8, AD-8,
AD-10; Story 4.4's lock columns and CAS, AD-16; Story 4.3 Part A's ``current_turn_id`` and its
no-precondition write for agent patches, AD-4; Story 3.2's ``submitted_at`` column and its
submitted-first list ordering).

``proposal`` has row-level security since migration 0009 (Story 4.3 Part B, AD-17): every method
here still opens its own ``engine.begin()``/``engine.connect()`` with no scope call of its own, and
none is needed -- ``adapters.db.scope.install_scope`` sets ``app.proposal_id``/``app.owner_oid``
with ``SET LOCAL`` on every transaction this engine opens, from a ``ContextVar`` the REST middleware
and the MCP adapter set around their own calls. The domain's ``ensure_owned`` (and the lock/turn
checks) remain the first guard; row-level security is the second, DB-enforced one underneath it.

Story 4.9: ``update_answers`` also logs every human override of a previously non-human answer into
``answer_overrides`` (migration 0012, AD-17), on the same connection and transaction as the
``proposal`` write it accompanies -- see ``adapters.db.answer_overrides`` and
``domain.answer_overrides``.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Column, FetchedValue, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncEngine

from adapters.db.answer_overrides import insert_overrides
from adapters.db.scope import Scope, scoped
from domain.answer_overrides import overrides_for
from domain.customer_numbers import format_customer_number
from domain.proposals import Proposal, ProposalStatus, SubmitResult

_metadata = MetaData()

# Read/write-side description of the table migration 0004 creates. `id`'s actual default
# (gen_random_uuid()) is defined once, in the migration; FetchedValue only tells SQLAlchemy one
# exists, so `insert()` never has to pass it.
proposal_table = Table(
    "proposal",
    _metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("customer_id", PGUUID(as_uuid=True)),
    Column("owner_oid", Text),
    Column("owner_seq", Integer),
    Column("schema_version", Integer),
    Column("status", Text),
    Column("revision", Integer),
    Column("conversation_id", Text),
    Column("answers", JSONB),
    Column("created_at", sa.TIMESTAMP(timezone=True)),
    Column("updated_at", sa.TIMESTAMP(timezone=True)),
    Column("lock_holder", Text),
    Column("lock_expires_at", sa.TIMESTAMP(timezone=True)),
    Column("current_turn_id", PGUUID(as_uuid=True)),
    Column("submitted_at", sa.TIMESTAMP(timezone=True)),
)

# Read/write-side description of the table migration 0004 creates (Story 1.8): one column per
# ``x-fill: db`` question, fixed in ``domain/customer_fields.py``, plus ``customer_number``
# (migration 0015, Story FORM-218: generated once at insert, read-only display data afterwards --
# never one of the ``x-fill: db`` columns, so it's never part of ``result.customer_values``). No
# row ever exists here until the submit-time upsert (Story 3.3, AD-13); nothing before this story
# writes to it.
customer_table = Table(
    "customer",
    _metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("first_name", Text),
    Column("date_of_birth", sa.Date()),
    Column("sex_at_birth", Text),
    Column("country_of_origin", Text),
    Column("country_of_residence", Text),
    Column("id_number", Text),
    Column("email", Text),
    Column("mobile", Text),
    Column("street_address", Text),
    Column("occupation", Text),
    Column("marital_status", Text),
    Column("income_range", Text),
    Column("last_name", Text),
    Column("city", Text),
    Column("postcode", Text),
    Column("customer_number", Text),
)

# The table migration 0011 creates (Story 3.3): one row per submitted proposal, the agent's own
# AI-rating feedback (never a live agent call -- Story 4.5 is not a dependency).
proposal_feedback_table = Table(
    "proposal_feedback",
    _metadata,
    Column("proposal_id", PGUUID(as_uuid=True), primary_key=True),
    Column("rating", Integer),
    Column("comment", Text),
    Column("given_by", Text),
    Column("at", sa.TIMESTAMP(timezone=True)),
)


def _proposal(row: Any) -> Proposal:
    return Proposal(
        id=row.id,
        customer_id=row.customer_id,
        owner_oid=row.owner_oid,
        owner_seq=row.owner_seq,
        schema_version=row.schema_version,
        status=ProposalStatus(row.status),
        revision=row.revision,
        conversation_id=row.conversation_id,
        answers=row.answers,
        created_at=row.created_at,
        updated_at=row.updated_at,
        lock_holder=row.lock_holder,
        lock_expires_at=row.lock_expires_at,
        current_turn_id=row.current_turn_id,
        submitted_at=row.submitted_at,
    )


class SqlProposalStore:
    """Creates and reads ``proposal`` rows with an async engine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self,
        *,
        owner_oid: str,
        schema_version: int,
        answers: Mapping[str, Mapping[str, Any]],
        now: datetime,
    ) -> Proposal:
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            # Two concurrent creates by the same agent can't collide on owner_seq (spec assumption);
            # the (owner_oid, owner_seq) unique constraint is the backstop.
            await connection.execute(
                sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(owner_oid)))
            )
            next_seq = (
                await connection.execute(
                    sa.select(
                        sa.func.coalesce(sa.func.max(columns.owner_seq), 0) + 1
                    ).where(columns.owner_oid == owner_oid)
                )
            ).scalar_one()
            row = (
                await connection.execute(
                    sa.insert(proposal_table)
                    .values(
                        customer_id=None,
                        owner_oid=owner_oid,
                        owner_seq=next_seq,
                        schema_version=schema_version,
                        status=ProposalStatus.DRAFT.value,
                        revision=0,
                        conversation_id=None,
                        answers=dict(answers),
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(proposal_table)
                )
            ).one()
        return _proposal(row)

    async def get(self, proposal_id: UUID) -> Proposal | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.select(proposal_table).where(proposal_table.c.id == proposal_id)
                )
            ).one_or_none()
        return _proposal(row) if row is not None else None

    async def customer_numbers(
        self, customer_ids: Sequence[UUID]
    ) -> dict[UUID, str | None]:
        """``customer_number`` for each of these customer ids, in one batched read (Story
        FORM-218): display-only join data the REST layer resolves onto ``DraftOut``/
        ``ProposalSummaryOut`` -- never stored on the domain ``Proposal`` itself, since it's a
        ``customer`` column, not proposal state. A ``customer_id`` with no such row (shouldn't
        happen; defensive only) is simply absent from the result, same as one never asked for."""
        ids = list({customer_id for customer_id in customer_ids if customer_id is not None})
        if not ids:
            return {}
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.select(customer_table.c.id, customer_table.c.customer_number).where(
                        customer_table.c.id.in_(ids)
                    )
                )
            ).all()
        return {row.id: row.customer_number for row in rows}

    async def list_for_owner(
        self, owner_oid: str, status: ProposalStatus
    ) -> Sequence[Proposal]:
        columns = proposal_table.c
        # Submitted: newest submitted_at first (Story 3.2, FR9); every other status keeps the
        # original newest-created-first ordering (spec Boundaries: "never change the draft-tab
        # ordering"). owner_seq is the tiebreak either way. nullslast() guards a submitted row
        # whose submitted_at hasn't been set yet (Story 3.3's real submit endpoint always sets
        # both together, but nothing in this story's domain enforces that pairing) -- Postgres
        # DESC defaults NULLS FIRST, which would otherwise sort it ahead of genuinely-newest rows.
        order = (
            (columns.submitted_at.desc().nullslast(), columns.owner_seq.desc())
            if status == ProposalStatus.SUBMITTED
            else (columns.created_at.desc(), columns.owner_seq.desc())
        )
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.select(proposal_table)
                    .where(
                        columns.owner_oid == owner_oid, columns.status == status.value
                    )
                    .order_by(*order)
                )
            ).all()
        return [_proposal(row) for row in rows]

    async def update_answers(
        self,
        proposal_id: UUID,
        expected_revision: int,
        apply: Callable[[Proposal], Proposal | None],
        *,
        model_deployment: str,
        overridden_by: str,
    ) -> Proposal | None:
        """One transaction: lock the row, run the pure ``apply`` callback, write its result (Story
        1.10, AD-6). The ``revision = expected_revision`` in the ``UPDATE``'s own ``WHERE`` is a
        second, cheap guard on top of the row lock; either one alone is already enough.

        Story 4.9 (AD-17): once the ``UPDATE`` succeeds, :func:`domain.answer_overrides.
        overrides_for` diffs the before/after ``Proposal`` (this store's `apply` is only ever
        :func:`domain.proposals.apply_answers`, the human PATCH path -- never the AI/MCP
        ``apply_agent_patch``) and any resulting rows are inserted into ``answer_overrides`` on
        this same ``connection``, before the transaction commits -- so a failed override insert
        rolls the whole write back, and a stale-revision write (which reaches neither branch below)
        logs nothing either.
        """
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    sa.select(proposal_table)
                    .where(columns.id == proposal_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                return None
            before = _proposal(row)
            updated = apply(before)
            if updated is None:
                return None
            result = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(
                        columns.id == proposal_id,
                        columns.revision == expected_revision,
                    )
                    .values(
                        revision=updated.revision,
                        answers=dict(updated.answers),
                        updated_at=updated.updated_at,
                    )
                    .returning(proposal_table)
                )
            ).one_or_none()
            if result is None:
                return None
            after = _proposal(result)
            overrides = overrides_for(
                before,
                after,
                model_deployment=model_deployment,
                overridden_by=overridden_by,
                now=after.updated_at,
            )
            await insert_overrides(connection, overrides)
        return after

    async def acquire_lock(
        self,
        proposal_id: UUID,
        session_id: str,
        now: datetime,
        expires_at: datetime,
        take_over: bool,
    ) -> Proposal | None:
        """One atomic ``UPDATE ... WHERE`` (Story 4.4, AD-16): the lock moves to ``session_id``
        exactly when the ``WHERE`` matches -- free (never held, or its ``lock_expires_at`` is
        before ``now``, both bound parameters, never ``now()``), already ``session_id``'s own, or
        -- with ``take_over`` -- any other live holder except ``ai``. Two simultaneous opens can't
        both win: only one ``UPDATE`` can match and return a row. When the ``WHERE`` doesn't match
        (blocked), a plain ``SELECT`` reports the row as it stands, so the caller can still tell
        the relative holder either way."""
        columns = proposal_table.c
        conditions = [
            columns.lock_holder.is_(None),
            columns.lock_expires_at < now,
            columns.lock_holder == session_id,
        ]
        if take_over:
            conditions.append(columns.lock_holder != "ai")
        async with self._engine.begin() as connection:
            updated = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(columns.id == proposal_id, sa.or_(*conditions))
                    # A human acquiring/renewing/taking over the lock never needs a stale
                    # current_turn_id kept around: clearing it here is Story 4.5's "next lock
                    # acquire clears stale current_turn_id" (AD-4, security.md rule 36) -- the
                    # only place a proposal moves back to human control, since a live ai lock is
                    # never matched by this WHERE (take_over excludes it, and a plain acquire only
                    # matches free/expired/already-hers).
                    .values(
                        lock_holder=session_id,
                        lock_expires_at=expires_at,
                        current_turn_id=None,
                    )
                    .returning(proposal_table)
                )
            ).one_or_none()
            if updated is None:
                updated = (
                    await connection.execute(
                        sa.select(proposal_table).where(columns.id == proposal_id)
                    )
                ).one_or_none()
            if updated is None:
                return None
        return _proposal(updated)

    async def apply_agent_patch(
        self,
        proposal_id: UUID,
        apply: Callable[[Proposal], Proposal | None],
    ) -> Proposal | None:
        """Like ``update_answers``, but with no client-supplied ``expected_revision`` (Story 4.3,
        AD-3): the ``SELECT ... FOR UPDATE`` row lock is the only guard on the ``UPDATE``'s own
        ``WHERE``, since the AI never reads a revision to send back. Whatever ``apply`` raises
        (a turn-binding or submitted-proposal ``DomainError``) propagates out and rolls the
        transaction back, same as ``update_answers``."""
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    sa.select(proposal_table)
                    .where(columns.id == proposal_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                return None
            updated = apply(_proposal(row))
            if updated is None:
                return None
            result = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(columns.id == proposal_id)
                    .values(
                        revision=updated.revision,
                        answers=dict(updated.answers),
                        updated_at=updated.updated_at,
                    )
                    .returning(proposal_table)
                )
            ).one()
        return _proposal(result)

    async def set_turn(
        self,
        proposal_id: UUID,
        *,
        lock_holder: str | None,
        lock_expires_at: datetime | None,
        current_turn_id: UUID | None,
    ) -> Proposal | None:
        """Write the lock/turn columns directly, no CAS and no precondition (Story 4.3): test-only
        plumbing for ``domain.proposals.begin_turn``/``end_turn`` -- no REST route calls this."""
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            updated = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(columns.id == proposal_id)
                    .values(
                        lock_holder=lock_holder,
                        lock_expires_at=lock_expires_at,
                        current_turn_id=current_turn_id,
                    )
                    .returning(proposal_table)
                )
            ).one_or_none()
            if updated is None:
                return None
        return _proposal(updated)

    async def begin_chat_turn(
        self,
        proposal_id: UUID,
        apply: Callable[[Proposal], Proposal],
    ) -> Proposal | None:
        """The Story 4.5 atomic turn-start seam: a ``SELECT ... FOR UPDATE`` row lock (same
        pattern as ``apply_agent_patch``), ``apply`` decides or raises, and only
        ``lock_holder``/``lock_expires_at``/``current_turn_id`` are written -- never
        ``revision``/``answers``, so this can never collide with a human PATCH or an AI
        ``patch_draft`` mid-turn."""
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    sa.select(proposal_table)
                    .where(columns.id == proposal_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                return None
            updated = apply(_proposal(row))
            result = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(columns.id == proposal_id)
                    .values(
                        lock_holder=updated.lock_holder,
                        lock_expires_at=updated.lock_expires_at,
                        current_turn_id=updated.current_turn_id,
                    )
                    .returning(proposal_table)
                )
            ).one()
        return _proposal(result)

    async def ensure_conversation(self, proposal_id: UUID, conversation_id: str) -> str:
        """The AD-9 conditional ``UPDATE ... WHERE conversation_id IS NULL``: one atomic write
        that only ever succeeds once per proposal; the race loser's own ``UPDATE`` matches no row,
        so it falls back to a plain ``SELECT`` and reuses whatever is already stored."""
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            won = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(columns.id == proposal_id, columns.conversation_id.is_(None))
                    .values(conversation_id=conversation_id)
                    .returning(columns.conversation_id)
                )
            ).scalar_one_or_none()
            if won is not None:
                return won
            stored = (
                await connection.execute(
                    sa.select(columns.conversation_id).where(columns.id == proposal_id)
                )
            ).scalar_one()
        return stored

    async def link_customer(
        self,
        proposal_id: UUID,
        customer_id: UUID,
        apply: Callable[[Proposal, Mapping[str, Any] | None], Proposal],
    ) -> Proposal | None:
        """One transaction (Story 5.2, AD-13): lock the proposal row (same ``SELECT ... FOR
        UPDATE`` pattern as ``apply_agent_patch``), read the ``customer`` row by ``customer_id``
        on this same connection (``None`` if no such row -- an unknown id is caught atomically,
        same transaction as the proposal lock), call ``apply(current, customer_row)`` and write
        only its ``revision``/``answers``/``customer_id``/``updated_at``. Whatever ``apply``
        raises (a turn-binding, submitted-proposal or unknown-customer ``DomainError``) propagates
        and rolls the transaction back, same as ``apply_agent_patch``."""
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    sa.select(proposal_table)
                    .where(columns.id == proposal_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                return None
            customer_row = (
                await connection.execute(
                    sa.select(customer_table).where(customer_table.c.id == customer_id)
                )
            ).mappings().one_or_none()
            updated = apply(_proposal(row), customer_row)
            result = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(columns.id == proposal_id)
                    .values(
                        revision=updated.revision,
                        answers=dict(updated.answers),
                        customer_id=updated.customer_id,
                        updated_at=updated.updated_at,
                    )
                    .returning(proposal_table)
                )
            ).one()
        return _proposal(result)

    async def submit(
        self,
        proposal_id: UUID,
        expected_revision: int,
        apply: Callable[[Proposal], Awaitable[SubmitResult | None]],
    ) -> Proposal | None:
        """One transaction (Story 3.3, AD-8, AD-13): lock the row, ``await`` the pure ``apply``
        callback, then write the ``customer`` upsert, the ``proposal_feedback`` insert and the
        proposal's own update. The ``customer`` upsert inserts when this proposal had no
        ``customer_id`` before this call (the value ``apply`` returned is then a freshly generated
        one, AD-13) and updates the existing row otherwise -- never both, and never a second
        ``customer`` row for the same proposal. Whatever ``apply`` raises (a check failure)
        propagates and rolls the whole transaction back, same as ``apply_agent_patch``."""
        columns = proposal_table.c
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    sa.select(proposal_table)
                    .where(columns.id == proposal_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                return None
            current = _proposal(row)
            result = await apply(current)
            if result is None:
                return None
            updated = result.proposal
            if current.customer_id is None:
                # A brand-new customer (Story FORM-218, AD-13): draw the next sequence value and
                # format its customer_number here, in the same transaction as the insert it
                # numbers -- domain/proposals.py never touches the sequence itself (AD-2, its own
                # docstring).
                sequence_value = (
                    await connection.execute(sa.text("SELECT nextval('customer_number_seq')"))
                ).scalar_one()
                await connection.execute(
                    sa.insert(customer_table).values(
                        id=updated.customer_id,
                        customer_number=format_customer_number(sequence_value),
                        **result.customer_values,
                    )
                )
            else:
                await connection.execute(
                    sa.update(customer_table)
                    .where(customer_table.c.id == current.customer_id)
                    .values(**result.customer_values)
                )
            await connection.execute(
                sa.insert(proposal_feedback_table).values(
                    proposal_id=proposal_id,
                    rating=result.feedback.rating,
                    comment=result.feedback.comment,
                    given_by=updated.owner_oid,
                    at=updated.updated_at,
                )
            )
            updated_row = (
                await connection.execute(
                    sa.update(proposal_table)
                    .where(
                        columns.id == proposal_id,
                        columns.revision == expected_revision,
                    )
                    .values(
                        revision=updated.revision,
                        answers=dict(updated.answers),
                        updated_at=updated.updated_at,
                        status=updated.status.value,
                        submitted_at=updated.submitted_at,
                        customer_id=updated.customer_id,
                    )
                    .returning(proposal_table)
                )
            ).one_or_none()
            if updated_row is None:
                return None
        return _proposal(updated_row)

    async def delete(self, proposal_id: UUID, owner_oid: str) -> bool:
        """One atomic hard delete (Story FORM-227, migration 0016): ``answer_overrides`` and
        ``proposal_feedback`` cascade with the ``proposal`` row at the database level, in this same
        transaction -- never a second application-level delete step.

        Nests ``Scope(proposal_id=proposal_id, owner_oid=owner_oid)`` around this transaction, on
        top of whatever the REST middleware's own request-wide ``scoped(for_owner(...))`` already
        set: the cascade-fired ``DELETE`` on ``answer_overrides`` is authorized by its
        ``proposal_id``-keyed row-level security policy, not its ``owner_oid``-keyed one -- that
        one's ``EXISTS (SELECT ... FROM proposal ...)`` check is no longer reliably true once the
        parent row is mid-cascade (spec Boundaries; integration-tested against real Postgres in
        ``tests/adapters/db/test_rls.py``, never only reasoned about)."""
        columns = proposal_table.c
        with scoped(Scope(proposal_id=proposal_id, owner_oid=owner_oid)):
            async with self._engine.begin() as connection:
                result = (
                    await connection.execute(
                        sa.delete(proposal_table)
                        .where(columns.id == proposal_id)
                        .returning(columns.id)
                    )
                ).one_or_none()
        return result is not None
