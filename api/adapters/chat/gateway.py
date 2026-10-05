"""The ``AgentGateway`` seam (Story 4.5, spine AD-9, AD-18): every Foundry call -- Responses
create/stream, conversation create, chat history read -- goes through this one interface. A
production call (``foundry.FoundryAgentGateway``) and a test call (``stub.StubAgentGateway``) are
otherwise indistinguishable to ``adapters.chat.turns``.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol


class GatewayError(Exception):
    """A turn's reply failed or timed out mid-stream (Story 4.5): the answers any scripted MCP
    write already committed stay saved (the caller's turn ends the same way either way), and the
    caller relays this as one SSE ``error {code, message}`` event -- never a 500, and the web app
    shows its own fixed failure message regardless of ``message`` (EXPERIENCE.md "Failure/cutoff",
    UX-DR: no red banner)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgentGateway(Protocol):
    """One proposal-agnostic seam to the hosted agent (AD-9, AD-18): nothing here ever sees a
    proposal id -- the turn token (``turn_token``) is the only thing that binds a call to one."""

    async def get_or_create_conversation(self) -> str:
        """Create a fresh Foundry conversation and return its id (AD-9). The caller stores it only
        through the AD-9 conditional ``UPDATE ... WHERE conversation_id IS NULL``; a race loser's
        own conversation id is simply never stored (Foundry keeps it, unused -- this seam has no
        "delete a conversation" operation, and AD-9 doesn't ask for one)."""
        ...

    async def get_history(self, conversation_id: str) -> Sequence[dict[str, Any]]:
        """The conversation's messages, oldest first, for ``GET /api/proposals/:id/chat`` (AD-9:
        "GET reads history from Foundry with owner check" -- the owner check is the REST route's
        job, this seam just reads)."""
        ...

    def stream(
        self,
        *,
        conversation_id: str,
        message: str,
        turn_token: str,
        traceparent: str | None,
    ) -> AsyncIterator[str]:
        """Send ``message`` to the hosted agent on ``conversation_id`` and yield its reply as text
        chunks (AD-4: ``turn_token`` is sent as ``x-client-turn-token``, never in ``metadata`` or
        model context; ``traceparent`` propagates the one trace a turn shares with the hosted
        agent run and its MCP calls, AD-9 Observability). Raises :class:`GatewayError` on a
        mid-stream failure or a timeout; any answers a scripted or real MCP write already applied
        before that point stay saved (Story 4.3's own transaction already committed them)."""
        ...
