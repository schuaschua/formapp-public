"""Row-level security scope (Story 4.3 Part B, spine AD-17, security.md rule 37).

The one shared function AD-17 requires: called automatically for every transaction opened on the
shared engine, never per repository method, so no call site can forget it. MCP sets ``app.proposal_id``
from the verified turn token's ``pid`` (``adapters.mcp.server._authorize``); REST and chat set
``app.owner_oid`` from the signed-in principal (``adapters.rest.middleware.AuthRequiredMiddleware``).
A transaction with neither set sees zero rows -- the row-level security policies migration 0009
creates have no fallback. This is a second, DB-enforced guard *under* the domain's own ownership and
lock checks (AD-2, AD-4, AD-8), not a replacement for them.

Story 7.2/FORM-238 adds a third, narrower scope: ``app.job_scope``, set only from
``jobs.feedback``'s own connection (never REST or MCP), gating migration 0019's
``proposal_feedback_api_job_scope`` policy -- the nightly job's deliberate, least-privilege
cross-owner read/update path over `proposal_feedback`, in place of a ``SECURITY DEFINER`` function
(AD-17's stated aversion to those). :func:`for_job` is the only factory for it; nothing outside
``jobs/`` calls it.

:func:`install_scope` registers a SQLAlchemy ``begin`` event on the engine's sync engine (the async
engine's own multiplexed sync engine, the documented way to hook Core-level events on an
``AsyncEngine``): it fires before any statement runs in a new transaction, on every connection
checked out of the pool, and reads the active :class:`Scope` from a ``ContextVar`` -- so
``SqlProposalStore`` and ``SqlProductCatalogue``'s own ~7 methods never call this directly and can't
be edited to forget it.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class Scope:
    """The active request's row-level security scope (AD-17): a proposal id (MCP), an owner oid
    (REST and chat), the nightly feedback job's own ``job`` flag (Story 7.2), or -- in principle --
    more than one at a time; never none once a request or the job has scoped it."""

    proposal_id: UUID | None = None
    owner_oid: str | None = None
    job: bool = False


_SCOPE: ContextVar["Scope | None"] = ContextVar("formapp_rls_scope", default=None)

# set_config(..., true): SET LOCAL, so the value never outlives this one transaction, whatever
# connection pooling does with the underlying connection afterwards.
_SET_PROPOSAL_ID = text("SELECT set_config('app.proposal_id', :value, true)")
_SET_OWNER_OID = text("SELECT set_config('app.owner_oid', :value, true)")
_SET_JOB_SCOPE = text("SELECT set_config('app.job_scope', :value, true)")


def for_proposal(proposal_id: UUID) -> Scope:
    """MCP's scope: only the one proposal the caller's turn token names (AD-4, AD-17)."""
    return Scope(proposal_id=proposal_id)


def for_owner(owner_oid: str) -> Scope:
    """REST and chat's scope: only the signed-in principal's own rows (AD-8, AD-17)."""
    return Scope(owner_oid=owner_oid)


def for_job() -> Scope:
    """The nightly feedback job's own scope (Story 7.2, AD-20): every owner's ``proposal_feedback``
    rows, through migration 0019's ``app.job_scope`` policy, never through a wider bypass. Only
    ``jobs.feedback`` calls this."""
    return Scope(job=True)


@contextmanager
def scoped(scope: Scope) -> Iterator[None]:
    """Make ``scope`` the active scope for every transaction opened while this is active, on
    whichever engine has :func:`install_scope` registered. Nests correctly (each call restores the
    previous scope on exit), though nothing in this story nests scopes."""
    token: Token[Scope | None] = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def install_scope(engine: AsyncEngine) -> None:
    """Register the ``begin`` event that sets the active scope before any query runs in a new
    transaction (AD-17). Call once, right after the engine is built; every
    ``SqlProposalStore``/``SqlProductCatalogue`` transaction on this engine is covered from then on,
    current and future, without editing their methods."""

    @event.listens_for(engine.sync_engine, "begin")
    def _set_scope(connection: Any) -> None:
        scope = _SCOPE.get()
        if scope is None:
            # No scope: the row-level security policies have nothing to match, so this
            # transaction sees zero rows against `proposal` -- the AD-17 default-deny.
            return
        if scope.proposal_id is not None:
            connection.execute(_SET_PROPOSAL_ID, {"value": str(scope.proposal_id)})
        if scope.owner_oid is not None:
            connection.execute(_SET_OWNER_OID, {"value": scope.owner_oid})
        if scope.job:
            connection.execute(_SET_JOB_SCOPE, {"value": "true"})
