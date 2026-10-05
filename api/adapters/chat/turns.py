"""Chat-turn orchestration (Story 4.5, spine AD-4, AD-5, AD-9, AD-16, AD-18): opens a turn
(``open_chat_turn``) and relays one turn's reply as the AD-5 SSE events (``run_chat_turn``).

Reuses ``domain.proposals.start_chat_turn``/``end_turn``/``ProposalStore.begin_chat_turn`` and
``domain.turn_tokens.issue_turn_token`` for every lock/turn transition -- this module never moves
the lock or the turn id itself, only calls into those seams and relays whatever the
:class:`~adapters.chat.gateway.AgentGateway` yields.

Story 4.8: ``run_chat_turn`` bounds its wait for each gateway chunk (``STREAM_CHUNK_TIMEOUT``,
real wall-clock time -- not on the AD-18 Clock seam, which only covers domain-timed windows; a
stalled gateway that never raises is still a genuine cut-off), and always ends the turn -- moving
the lock back and clearing ``current_turn_id`` -- in a ``finally``, so a client disconnect
(Starlette cancels the streaming task while this generator is suspended at a ``yield``, which
propagates as ``CancelledError``/``GeneratorExit``, never caught by ``except Exception``) still
releases the lock instead of leaving it stuck on ``ai`` until the 5-minute safety expiry.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
from pydantic import SecretStr

from adapters.chat.gateway import AgentGateway, GatewayError
from adapters.chat.logging_events import log_turn_end, log_turn_start
from adapters.db.scope import for_owner, scoped
from domain.clock import Clock
from domain.proposals import (
    LOCK_DURATION,
    Proposal,
    ProposalNotFoundError,
    ProposalStore,
    end_turn,
    start_chat_turn,
)
from domain.turn_tokens import issue_turn_token

# Story 4.8: how long run_chat_turn waits for the *next* gateway chunk before treating the stream
# as cut off -- real wall-clock time (asyncio.wait_for), never the injectable Clock (AD-18 lists
# only domain-timed windows: lock/turn-token expiry, the throttle window, pricing age). Generous
# enough that a normal reply's own gaps never trip it; tests override it directly rather than
# waiting this long.
STREAM_CHUNK_TIMEOUT = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """One SSE event: ``event`` is exactly ``"delta"``, ``"done"`` or ``"error"`` (AD-5); ``data``
    is the JSON body to serialize alongside it."""

    event: str
    data: dict[str, Any]


async def open_chat_turn(
    *,
    store: ProposalStore,
    proposal_id: UUID,
    principal_oid: str,
    session_id: str,
    signing_key: SecretStr,
    clock: Clock,
) -> tuple[Proposal, str]:
    """Mint a turn token and atomically begin the turn (Story 4.5, AC1, AC6, AC7, AC8): returns
    the updated proposal (lock now ``ai``, ``current_turn_id`` == the token's own ``tid``) and the
    token itself.

    Raises ``ProposalNotFoundError`` (404, an unowned or unknown proposal -- no turn starts, AC6)
    before anything else, since :func:`domain.turn_tokens.issue_turn_token` checks ownership first;
    raises ``DomainError`` -- ``proposal_submitted``, ``turn_in_progress`` or ``lock_not_held`` --
    for every other rejection (AC6, AC7, AC8), with nothing changed either way.

    Unlike :func:`run_chat_turn`, every DB call here runs synchronously inside the normal
    ``POST /chat`` request, before its ``StreamingResponse`` is even constructed -- the automatic
    per-REST-request scoping hook (``adapters.rest.middleware.AuthRequiredMiddleware``, AD-17)
    already covers it; no explicit ``scoped(...)`` needed here.
    """
    token = await issue_turn_token(store, proposal_id, principal_oid, clock, signing_key)
    tid = UUID(jwt.decode(token, options={"verify_signature": False})["tid"])

    def apply(current: Proposal) -> Proposal:
        return start_chat_turn(current, session_id, tid, clock)

    updated = await store.begin_chat_turn(proposal_id, apply)
    if updated is None:  # pragma: no cover -- the row existed a moment ago (issue_turn_token)
        raise ProposalNotFoundError(proposal_id)
    return updated, token


async def run_chat_turn(
    *,
    store: ProposalStore,
    gateway: AgentGateway,
    proposal: Proposal,
    token: str,
    session_id: str,
    message: str,
    clock: Clock,
    traceparent: str | None,
    stream_chunk_timeout: timedelta = STREAM_CHUNK_TIMEOUT,
) -> AsyncIterator[ChatEvent]:
    """Relay the gateway's reply as SSE events and end the turn either way (Story 4.5, AC1, AC5,
    AC9, AC13, AC14; Story 4.8's failure paths): the conversation is created on first turn (AD-9's
    conditional ``UPDATE``), then every ``delta {text}`` chunk the gateway yields is relayed as it
    arrives, then exactly one ``done {revision}`` (stream finished cleanly) or ``error {code,
    message}`` (the gateway raised, or went quiet longer than ``stream_chunk_timeout`` -- a
    cut-off) -- and the lock always goes back to ``session_id`` with ``current_turn_id`` cleared,
    whatever happens (AD-16, in a ``finally`` -- this module's own docstring), before that last
    event is even yielded, so the web app's next draft re-fetch already sees the released lock.

    A client disconnect (or any other cancellation of this generator while it's suspended at a
    ``yield``) still runs the ``finally`` below -- moving the lock back and logging turn-end -- but
    never reaches the trailing ``yield``s (Story 4.8: "the lock is still released"; nothing is
    listening for a last event anyway).
    """
    turn_id = proposal.current_turn_id
    log_turn_start(
        proposal_id=proposal.id,
        turn_id=turn_id,
        conversation_id=proposal.conversation_id,
    )

    conversation_id = proposal.conversation_id
    if conversation_id is None:
        created = await gateway.get_or_create_conversation()
        # This write happens after the SSE response has already started streaming, outside the
        # request that opened it -- scope it explicitly rather than relying on whatever the
        # per-request middleware's scope happens to still be active. A chat-adapter transaction
        # scopes by owner, same as a normal REST write (AD-17, security.md rule 37).
        with scoped(for_owner(proposal.owner_oid)):
            conversation_id = await store.ensure_conversation(proposal.id, created)

    failure: GatewayError | None = None
    try:
        stream = gateway.stream(
            conversation_id=conversation_id,
            message=message,
            turn_token=token,
            traceparent=traceparent,
        ).__aiter__()
        try:
            while True:
                try:
                    async with asyncio.timeout(stream_chunk_timeout.total_seconds()):
                        chunk = await stream.__anext__()
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    raise GatewayError(
                        "timeout", "The agent timed out."
                    ) from None
                yield ChatEvent("delta", {"text": chunk})
        finally:
            await stream.aclose()
    except GatewayError as exc:
        failure = exc
    except Exception:  # noqa: BLE001 -- any other failure still ends the turn cleanly, never a 500
        failure = GatewayError(
            "agent_error", "The agent failed unexpectedly."
        )
    finally:
        # Story 4.8: always runs, including when this generator is closed/cancelled mid-stream
        # (a client disconnect) -- see this module's docstring. GeneratorExit/CancelledError skip
        # the except clauses above (neither is an Exception) but never this finally.
        now = clock.now()
        # Same reasoning as ensure_conversation above -- this write (moving the lock back and
        # clearing current_turn_id) happens during/after SSE streaming (AD-17, security.md rule 37).
        with scoped(for_owner(proposal.owner_oid)):
            ended = await end_turn(
                store,
                proposal.id,
                lock_holder=session_id,
                lock_expires_at=now + LOCK_DURATION,
            )
        log_turn_end(
            proposal_id=proposal.id, turn_id=turn_id, conversation_id=conversation_id
        )

    if failure is not None:
        yield ChatEvent("error", {"code": failure.code, "message": failure.message})
        return
    revision = ended.revision if ended is not None else proposal.revision
    yield ChatEvent("done", {"revision": revision})
