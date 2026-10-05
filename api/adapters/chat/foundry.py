"""The production ``AgentGateway`` (Story 4.5, spine AD-9, AD-18): calls the hosted agent's
Responses endpoint -- ``{FOUNDRY_PROJECT_ENDPOINT}/agents/{FOUNDRY_AGENT_NAME}/endpoint/protocols/
openai/responses?api-version=v1`` (the same URL shape the Story 4.1 deploy smoke check already
proves) -- through the OpenAI-compatible ``openai`` SDK's async client, authenticated as ``api``'s
managed identity (the ``Foundry User`` role already granted in ``infra/demo/foundation``, scope
``https://ai.azure.com/.default``).

Never exercised against real Azure in any test (no test may call Azure, spine AD-18); the unit
tests here inject a fake ``client``/``credential`` instead, exactly the seam this class exposes for
that purpose.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from openai import AsyncOpenAI
from openai.types.responses import ResponseStreamEvent

from adapters.chat.gateway import GatewayError

# The token audience the hosted agent's Responses endpoint accepts (epic-4-context.md, AC1).
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
_API_VERSION = "v1"


class _TokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> Any: ...


class FoundryAgentGateway:
    """See this module's docstring. ``client``/``credential`` are constructor seams for tests
    (spine AD-18); production code (``adapters.rest.app``) leaves both at their defaults."""

    def __init__(
        self,
        *,
        project_endpoint: str,
        agent_name: str,
        model: str,
        credential: _TokenCredential | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        # Built lazily in _token() when not given: azure-identity's async transport needs
        # aiohttp (an api/ dependency since the 2026-09-27 deploy crashed on its absence). Test
        # mode never reaches this class at all (AD-18).
        self._credential = credential
        base_url = (
            f"{project_endpoint.rstrip('/')}/agents/{agent_name}"
            "/endpoint/protocols/openai"
        )
        self._client = client or AsyncOpenAI(
            api_key=self._token,
            base_url=base_url,
            default_query={"api-version": _API_VERSION},
        )

    @staticmethod
    def _default_credential() -> _TokenCredential:
        from azure.identity.aio import DefaultAzureCredential

        return DefaultAzureCredential()

    async def _token(self) -> str:
        if self._credential is None:
            self._credential = self._default_credential()
        token = await self._credential.get_token(FOUNDRY_SCOPE)
        return str(token.token)

    async def get_or_create_conversation(self) -> str:
        conversation = await self._client.conversations.create()
        return conversation.id

    async def get_history(self, conversation_id: str) -> Sequence[dict[str, Any]]:
        """Best-effort text extraction (Story 4.6 gives this its real wire shape; 4.5 only needs
        the ``AgentGateway`` seam to exist and read from Foundry, AD-9)."""
        history: list[dict[str, Any]] = []
        async for item in self._client.conversations.items.list(conversation_id):
            role = getattr(item, "role", None)
            text = _item_text(item)
            if role is not None and text:
                history.append({"role": role, "text": text})
        return history

    async def stream(
        self,
        *,
        conversation_id: str,
        message: str,
        turn_token: str,
        traceparent: str | None,
    ) -> AsyncIterator[str]:
        headers = {"x-client-turn-token": turn_token}
        if traceparent:
            headers["traceparent"] = traceparent
        try:
            events = await self._client.responses.create(
                model=self._model,
                conversation=conversation_id,
                input=message,
                stream=True,
                extra_headers=headers,
            )
            async for event in events:
                delta = _event_delta(event)
                if delta:
                    yield delta
                if event.type in ("response.failed", "response.incomplete", "error"):
                    raise GatewayError(
                        "agent_error", "The agent couldn't finish this reply."
                    )
        except GatewayError:
            raise
        except Exception as exc:  # noqa: BLE001 -- any SDK/network failure ends the turn cleanly
            raise GatewayError(
                "agent_error", "The agent couldn't finish this reply."
            ) from exc


def _event_delta(event: ResponseStreamEvent) -> str | None:
    if event.type == "response.output_text.delta":
        return str(event.delta)
    return None


def _item_text(item: Any) -> str:
    content = getattr(item, "content", None)
    if not isinstance(content, list):
        return ""
    parts = [
        str(getattr(part, "text", ""))
        for part in content
        if getattr(part, "text", None)
    ]
    return "".join(parts)
