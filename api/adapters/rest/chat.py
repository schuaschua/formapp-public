"""``POST/GET /api/proposals/:id/chat`` (Story 4.5, 4.6, spine AD-4, AD-5, AD-9, AD-16, AD-18).

``POST`` runs every synchronous check (ownership, submitted, turn-in-progress, lock) before the
streamed response ever starts, through ``adapters.chat.turns.open_chat_turn`` -- a rejection is a
plain 404/409 JSON body (the existing ``DomainError``/``ProposalNotFoundError`` handlers,
``adapters.rest.errors``), never something embedded in the SSE stream. Only once the turn has
actually begun does the response become ``text/event-stream``, relaying
``adapters.chat.turns.run_chat_turn``'s events.

``GET`` reads the conversation's history from the ``AgentGateway`` (AD-9: "reads history from
Foundry with owner check"); an unstarted conversation (no chat yet) is an empty list. Story 4.6,
CAP-4: the AI's opening message (``domain.checklist.opening_message``) is always prepended
(a short welcome since Story 4.10 / FORM-235) -- it is never a model call, uses no
throttle slot, needs no lock, and is never written to the Foundry conversation itself (AD-9), so it
always stays first however much real history follows it.
"""

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from opentelemetry import propagate
from pydantic import BaseModel

from adapters.chat.turns import ChatEvent, open_chat_turn, run_chat_turn
from adapters.db.proposals import SqlProposalStore
from adapters.db.throttle import SqlThrottleStore
from adapters.rest.middleware import SESSION_HEADER
from adapters.rest.principal import current_principal
from domain.checklist import opening_message
from domain.principal import Principal
from domain.proposals import ensure_owned
from domain.throttle import check_and_record

router = APIRouter()


class ChatIn(BaseModel):
    """``POST /api/proposals/:id/chat`` body: the agent's own message."""

    message: str


def _session_id(request: Request) -> str:
    """The caller's per-tab lock identity (Story 4.4, AD-16); required by
    ``SessionHeaderMiddleware`` on every non-GET call already."""
    return request.headers.get(SESSION_HEADER, "")


def _store(request: Request) -> SqlProposalStore:
    return SqlProposalStore(request.app.state.engine)


def _throttle_store(request: Request) -> SqlThrottleStore:
    return SqlThrottleStore(request.app.state.engine)


def _current_traceparent() -> str | None:
    """The current span's W3C ``traceparent`` (Story 4.5, AC13, Observability): empty when
    telemetry is off (no span is ever recording, so nothing is propagated) -- the gateway then
    sends no ``traceparent`` header at all, same as any call outside a request."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier.get("traceparent")


def _sse(event: ChatEvent) -> str:
    """One SSE frame: ``event: <name>\\ndata: <json>\\n\\n`` (AD-5's exactly three event types)."""
    return f"event: {event.event}\ndata: {json.dumps(event.data)}\n\n"


@router.post("/api/proposals/{proposal_id}/chat")
async def post_chat(
    request: Request,
    proposal_id: UUID,
    body: ChatIn,
    principal: Annotated[Principal, Depends(current_principal)],
) -> StreamingResponse:
    """Begin a chat turn and relay its reply as SSE (Story 4.5, AC1, AC3, AC5-AC9, AC11; Story
    4.8's throttle, AD-9)."""
    store = _store(request)
    settings = request.app.state.settings
    clock = request.app.state.clock
    session_id = _session_id(request)

    # Story 4.8: checked -- and, if allowed, recorded -- before open_chat_turn, so a throttled
    # request never takes the lock and is never counted (raises ThrottledError -> the dedicated
    # 429, adapters.rest.errors).
    await check_and_record(_throttle_store(request), principal.oid, clock)

    proposal, token = await open_chat_turn(
        store=store,
        proposal_id=proposal_id,
        principal_oid=principal.oid,
        session_id=session_id,
        signing_key=settings.turn_token_signing_key,
        clock=clock,
    )
    gateway = request.app.state.agent_gateway
    traceparent = _current_traceparent()

    async def events() -> Any:
        async for event in run_chat_turn(
            store=store,
            gateway=gateway,
            proposal=proposal,
            token=token,
            session_id=session_id,
            message=body.message,
            clock=clock,
            traceparent=traceparent,
        ):
            yield _sse(event)

    return StreamingResponse(events(), media_type="text/event-stream")


def _checklist_message(principal: Principal) -> dict[str, Any]:
    """The opening message (Story 4.6/4.10, FR63, AD-9), as a chat message shaped like any other
    -- ``role: "assistant"`` -- so the web app renders it as an ordinary "formapp AI" bubble, the
    first one, with no client-side special case."""
    return {"role": "assistant", "text": opening_message(principal.first_name)}


@router.get("/api/proposals/{proposal_id}/chat")
async def get_chat(
    request: Request,
    proposal_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict[str, Any]:
    """The opening checklist, then the conversation's history, oldest first; no further history
    before the first turn (Story 4.5, 4.6, AD-7, AD-9)."""
    proposal = await ensure_owned(_store(request), proposal_id, principal.oid)
    checklist = _checklist_message(principal)
    if proposal.conversation_id is None:
        return {"messages": [checklist]}
    gateway = request.app.state.agent_gateway
    messages = await gateway.get_history(proposal.conversation_id)
    return {"messages": [checklist, *messages]}
