"""The test-only ``AgentGateway`` (Story 4.5, AD-18): scripted reply text and a scripted MCP tool
plan, mid-stream failure and timeout, driven by the injectable ``Clock`` -- never a real Foundry
call, never a sleep.

A script step is either delta reply text or a ``patch_draft``-shaped write. A patch step is applied
through the exact same domain seam the real ``/mcp`` server uses (``domain.turn_tokens.resolve_turn``
then ``domain.proposals.apply_agent_patch``, written back through
``ProposalStore.apply_agent_patch``) so it honours every rule a real MCP call would --
``human_locked``, ``not_agent_writable``, an inactive or unknown field, all of it -- and logs the
write the same way (``adapters.chat.logging_events.log_ai_write``), without needing a real
Streamable HTTP round trip to this same process. This also means an invalid or stale turn token
(the same failure a real MCP call would hit) surfaces here as a :class:`~adapters.chat.gateway.GatewayError`,
never a silent no-op.

``create_app`` builds one of these automatically whenever ``FORMAPP_TEST_MODE`` is on and no
``agent_gateway`` is given (local runs, the Playwright journeys, CI's ``api``/``e2e`` sections):
its default script is a short canned reply that also fills the customer's first name (``C1``), so
those runs see the chat panel actually do something without a real Foundry call.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from adapters.chat.gateway import GatewayError
from adapters.chat.logging_events import log_ai_write
from adapters.db.products import SqlProductCatalogue
from adapters.db.proposals import SqlProposalStore
from adapters.db.scope import for_proposal, scoped
from domain.clock import Clock
from domain.errors import DomainError
from domain.products import list_products
from domain.proposals import apply_agent_patch
from domain.schema import load_schema
from domain.turn_tokens import TurnTokenError, decode_turn_token, resolve_turn


@dataclass(frozen=True, slots=True)
class DeltaStep:
    """One SSE ``delta`` chunk of reply text."""

    text: str


@dataclass(frozen=True, slots=True)
class PatchStep:
    """One scripted ``patch_draft``-shaped write, applied through the real domain rules."""

    answers: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FailStep:
    """The stream fails here (mid-stream failure or a timeout -- the same shape either way);
    ``code`` is whatever the caller wants to see on the SSE ``error`` event (e.g. ``"timeout"``)."""

    code: str = "agent_error"
    message: str = "The agent failed to reply."


@dataclass(frozen=True, slots=True)
class HangStep:
    """The stream goes quiet here for ``seconds`` without yielding or raising -- a genuine cut-off
    (Story 4.8): ``run_chat_turn``'s own bounded wait (``STREAM_CHUNK_TIMEOUT``) is what actually
    ends the turn, never this step itself, so tests pass a tiny ``stream_chunk_timeout`` directly
    rather than waiting out a real production-sized one (spec Boundaries: never sleep in a test to
    wait for time-based behaviour -- this sleeps only long enough to be safely longer than that
    tiny override, not to wait out anything itself)."""

    seconds: float = 5.0


ScriptStep = DeltaStep | PatchStep | FailStep | HangStep

# The default script an auto-built stub (local runs, Playwright, no explicit test script) plays:
# a short canned reply, and one scripted C1 write so the chat panel visibly does something.
DEFAULT_SCRIPT: tuple[ScriptStep, ...] = (
    DeltaStep("Got it. "),
    DeltaStep("I've noted that for the proposal."),
    PatchStep({"C1": "Ally"}),
)


class StubAgentGateway:
    """Scripted, in-process ``AgentGateway`` (AD-18): see this module's docstring."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        signing_key: SecretStr,
        clock: Clock,
        script: Sequence[ScriptStep] | None = None,
    ) -> None:
        # Public so a test can drive the exact same store directly (e.g. a conditional-write race
        # against `ensure_conversation`) without building a second one from the same engine.
        self.store = SqlProposalStore(engine)
        self._catalogue = SqlProductCatalogue(engine)
        self._signing_key = signing_key
        self._clock = clock
        self._script = tuple(script) if script is not None else DEFAULT_SCRIPT
        self._conversations: dict[str, list[dict[str, Any]]] = {}
        # What the last stream() call actually received, for tests that check propagation
        # (Story 4.5, AC13) without needing a real trace exporter.
        self.received_turn_tokens: list[str] = []
        self.received_traceparents: list[str | None] = []

    async def get_or_create_conversation(self) -> str:
        conversation_id = f"synthetic-conversation-{uuid4()}"
        self._conversations[conversation_id] = []
        return conversation_id

    async def get_history(self, conversation_id: str) -> Sequence[dict[str, Any]]:
        return list(self._conversations.get(conversation_id, []))

    async def _apply_patch(self, turn_token: str, answers: dict[str, Any]) -> None:
        try:
            claims = decode_turn_token(turn_token, self._signing_key, self._clock)
        except TurnTokenError as exc:
            raise GatewayError(
                "agent_error", "The agent's turn token was rejected."
            ) from exc
        # This scripted patch step stands in for a real MCP patch_draft tool call and runs during
        # run_chat_turn's SSE streaming, outside the request that opened the turn -- scope the read
        # (resolve_turn) and the write (apply_agent_patch) together, exactly as
        # adapters.mcp.server's real _authorize does around a real tool call (AD-17,
        # security.md rule 37).
        try:
            with scoped(for_proposal(claims.pid)):
                proposal = await resolve_turn(
                    self.store, turn_token, self._signing_key, self._clock
                )
                schema = load_schema(proposal.schema_version)
                products = await list_products(self._catalogue)
                outcome: dict[str, list[Any]] = {}

                def apply(current: Any) -> Any:
                    updated, applied, errors = apply_agent_patch(
                        schema, current, answers, self._clock, products, claims
                    )
                    outcome["applied"] = applied
                    outcome["errors"] = errors
                    return updated

                updated = await self.store.apply_agent_patch(proposal.id, apply)
        except (TurnTokenError, DomainError) as exc:
            raise GatewayError(
                "agent_error", "The agent's turn token was rejected."
            ) from exc
        if updated is not None and outcome.get("applied"):
            log_ai_write(
                proposal_id=updated.id,
                turn_id=claims.tid,
                conversation_id=updated.conversation_id,
            )

    async def stream(
        self,
        *,
        conversation_id: str,
        message: str,
        turn_token: str,
        traceparent: str | None,
    ) -> AsyncIterator[str]:
        self.received_turn_tokens.append(turn_token)
        self.received_traceparents.append(traceparent)
        history = self._conversations.setdefault(conversation_id, [])
        history.append({"role": "user", "text": message})
        reply = ""
        for step in self._script:
            if isinstance(step, DeltaStep):
                reply += step.text
                yield step.text
            elif isinstance(step, PatchStep):
                await self._apply_patch(turn_token, step.answers)
            elif isinstance(step, HangStep):
                await asyncio.sleep(step.seconds)
            else:
                raise GatewayError(step.code, step.message)
        history.append({"role": "assistant", "text": reply})
