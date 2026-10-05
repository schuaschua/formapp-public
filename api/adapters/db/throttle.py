"""The stored ``chat_turn_log`` row, for the domain's ``ThrottleStore`` port (Story 4.8, migration
0017, spine AD-9, AD-17).

``chat_turn_log`` has row-level security since the same migration creates it (AD-17): this store
opens its own ``engine.begin()`` with no scope call of its own, same as ``SqlProposalStore``
(``adapters/db/proposals.py``'s own docstring) -- ``adapters.db.scope.install_scope`` already sets
``app.owner_oid`` with ``SET LOCAL`` on every transaction this engine opens, from the REST
middleware's own scope around the whole request (``open_chat_turn``'s docstring: the throttle check
runs synchronously inside that same request, before any ``StreamingResponse`` starts).
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Column, FetchedValue, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncEngine

_metadata = MetaData()

# Read/write-side description of the table migration 0017 creates.
chat_turn_log_table = Table(
    "chat_turn_log",
    _metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("oid", Text, nullable=False),
    Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
)


class SqlThrottleStore:
    """Implements ``domain.throttle.ThrottleStore`` against ``chat_turn_log``."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record_if_allowed(
        self, oid: str, now: datetime, window_start: datetime, limit: int
    ) -> datetime | None:
        columns = chat_turn_log_table.c
        async with self._engine.begin() as connection:
            # A session-local advisory lock keyed by oid, held for this transaction only
            # (pg_advisory_xact_lock releases automatically at COMMIT/ROLLBACK): serializes two
            # POST /chat calls racing for the same oid, so they can't both read "under the limit"
            # and both insert -- AD-9's "counted in PostgreSQL", not just stored there.
            await connection.execute(
                sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(oid)))
            )
            rows = (
                await connection.execute(
                    sa.select(columns.started_at)
                    .where(columns.oid == oid, columns.started_at >= window_start)
                    .order_by(columns.started_at.asc())
                )
            ).fetchall()
            if len(rows) >= limit:
                oldest: datetime = rows[0][0]
                return oldest
            await connection.execute(
                sa.insert(chat_turn_log_table).values(oid=oid, started_at=now)
            )
            return None
