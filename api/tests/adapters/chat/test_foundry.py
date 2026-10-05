"""Story 4.5: ``FoundryAgentGateway`` -- unit tests only, with a fake ``client``/``credential``
injected (spine AD-18: never a real Foundry/Azure call). Proves the request shape (base URL, the
turn token and traceparent as headers, the conversation id) and the response mapping (delta
extraction, a failed/errored stream becomes ``GatewayError``, history text extraction), not the
real ``openai`` SDK's own behaviour.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from adapters.chat.foundry import FOUNDRY_SCOPE, FoundryAgentGateway
from adapters.chat.gateway import GatewayError


class _FakeEvent:
    def __init__(self, type_: str, delta: str | None = None) -> None:
        self.type = type_
        self.delta = delta


class _FakeResponses:
    def __init__(self, events: list[_FakeEvent], calls: list[dict[str, Any]]) -> None:
        self._events = events
        self._calls = calls

    async def create(self, **kwargs: Any) -> Any:
        self._calls.append(kwargs)

        async def _stream() -> Any:
            for event in self._events:
                yield event

        return _stream()


class _FakeConversationItems:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def list(self, _conversation_id: str) -> Any:
        items = self._items

        async def _iter() -> Any:
            for item in items:
                yield item

        return _iter()


class _FakeConversations:
    def __init__(self, conversation_id: str, items: list[Any]) -> None:
        self._conversation_id = conversation_id
        self.items = _FakeConversationItems(items)

    async def create(self) -> Any:
        return SimpleNamespace(id=self._conversation_id)


class _FakeClient:
    def __init__(
        self,
        *,
        events: list[_FakeEvent] | None = None,
        conversation_id: str = "synthetic-conversation-1",
        items: list[Any] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = _FakeResponses(events or [], self.calls)
        self.conversations = _FakeConversations(conversation_id, items or [])


class _FakeCredential:
    def __init__(self, token: str = "synthetic-entra-token") -> None:
        self.requested_scopes: list[tuple[str, ...]] = []
        self._token = token

    async def get_token(self, *scopes: str) -> Any:
        self.requested_scopes.append(scopes)
        return SimpleNamespace(token=self._token)


def _gateway(client: _FakeClient, credential: _FakeCredential | None = None) -> FoundryAgentGateway:
    return FoundryAgentGateway(
        project_endpoint="https://synthetic-foundry.example.test/api/projects/formapp",
        agent_name="formapp-agent",
        model="synthetic-model",
        credential=credential or _FakeCredential(),
        client=client,  # type: ignore[arg-type]
    )


def test_get_or_create_conversation_returns_the_clients_id() -> None:
    client = _FakeClient(conversation_id="conv-xyz")
    gateway = _gateway(client)

    conversation_id = asyncio.run(gateway.get_or_create_conversation())

    assert conversation_id == "conv-xyz"


def test_stream_yields_only_text_delta_chunks() -> None:
    client = _FakeClient(
        events=[
            _FakeEvent("response.created"),
            _FakeEvent("response.output_text.delta", delta="Hello"),
            _FakeEvent("response.output_text.delta", delta=", world"),
            _FakeEvent("response.completed"),
        ]
    )
    gateway = _gateway(client)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in gateway.stream(
                conversation_id="conv-1",
                message="hi",
                turn_token="synthetic-turn-token",
                traceparent="00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
            )
        ]

    chunks = asyncio.run(collect())

    assert chunks == ["Hello", ", world"]
    call = client.calls[0]
    assert call["conversation"] == "conv-1"
    assert call["model"] == "synthetic-model"
    assert call["extra_headers"]["x-client-turn-token"] == "synthetic-turn-token"
    assert (
        call["extra_headers"]["traceparent"]
        == "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    )


def test_stream_omits_the_traceparent_header_when_none() -> None:
    client = _FakeClient(events=[_FakeEvent("response.completed")])
    gateway = _gateway(client)

    async def drain() -> None:
        async for _ in gateway.stream(
            conversation_id="conv-1", message="hi", turn_token="t", traceparent=None
        ):
            pass

    asyncio.run(drain())

    assert "traceparent" not in client.calls[0]["extra_headers"]


def test_stream_raises_gateway_error_on_a_failed_event() -> None:
    client = _FakeClient(
        events=[_FakeEvent("response.output_text.delta", delta="partial"), _FakeEvent("response.failed")]
    )
    gateway = _gateway(client)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in gateway.stream(
                conversation_id="conv-1", message="hi", turn_token="t", traceparent=None
            )
        ]

    with pytest.raises(GatewayError) as excinfo:
        asyncio.run(collect())
    assert excinfo.value.code == "agent_error"


def test_stream_wraps_any_sdk_exception_as_a_gateway_error() -> None:
    class _BrokenResponses:
        async def create(self, **_: Any) -> Any:
            raise RuntimeError("network exploded")

    client = _FakeClient()
    client.responses = _BrokenResponses()  # type: ignore[assignment]
    gateway = _gateway(client)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in gateway.stream(
                conversation_id="conv-1", message="hi", turn_token="t", traceparent=None
            )
        ]

    with pytest.raises(GatewayError):
        asyncio.run(collect())


def test_get_history_extracts_role_and_text() -> None:
    part = SimpleNamespace(text="hello there")
    item = SimpleNamespace(role="user", content=[part])
    client = _FakeClient(items=[item])
    gateway = _gateway(client)

    history = asyncio.run(gateway.get_history("conv-1"))

    assert history == [{"role": "user", "text": "hello there"}]


def test_get_history_skips_items_with_no_text() -> None:
    item = SimpleNamespace(role="assistant", content=[])
    client = _FakeClient(items=[item])
    gateway = _gateway(client)

    history = asyncio.run(gateway.get_history("conv-1"))

    assert history == []


def test_no_credential_given_defers_building_one_until_the_first_token_request() -> None:
    """Construction alone must never build a real credential (spine AD-18): that touches
    azure-identity's async transport machinery (needs ``aiohttp``, not a dependency of ``api/``),
    so it must wait for an actual ``stream()``/``get_history()`` call -- which a plain
    ``create_app()`` (every existing 401/403/route test included) never makes."""
    gateway = FoundryAgentGateway(
        project_endpoint="https://synthetic-foundry.example.test/api/projects/formapp",
        agent_name="formapp-agent",
        model="synthetic-model",
        client=_FakeClient(),  # type: ignore[arg-type]
    )

    assert gateway._credential is None  # noqa: SLF001 -- proving the deferred-build seam directly


def test_the_token_provider_requests_the_foundry_scope() -> None:
    client = _FakeClient(events=[_FakeEvent("response.completed")])
    credential = _FakeCredential()
    gateway = FoundryAgentGateway(
        project_endpoint="https://synthetic-foundry.example.test/api/projects/formapp",
        agent_name="formapp-agent",
        model="synthetic-model",
        credential=credential,
        client=client,  # type: ignore[arg-type]
    )

    async def drain() -> None:
        async for _ in gateway.stream(
            conversation_id="conv-1", message="hi", turn_token="t", traceparent=None
        ):
            pass
        # Force the api_key callable (the token provider) to run once, the way the real SDK would
        # when it needs a fresh bearer token for a request.
        await gateway._token()  # noqa: SLF001 -- exercising the constructor-injected seam directly

    asyncio.run(drain())

    assert credential.requested_scopes == [(FOUNDRY_SCOPE,)]


def test_demo_mode_builds_the_real_managed_identity_credential() -> None:
    """Regression (deploy 2026-09-27): outside test mode create_app() builds the async
    ManagedIdentityCredential at startup, which needs aiohttp; without it api crashed on start."""
    from azure.identity.aio import ManagedIdentityCredential
    from sqlalchemy.ext.asyncio import create_async_engine

    from adapters.clock import SystemClock
    from adapters.rest.app import _default_agent_gateway
    from tests.support import make_settings

    settings = make_settings(
        database_port=1,
        formapp_test_mode=False,
        azure_client_id="00000000-1111-2222-3333-444444444444",
        foundry_project_endpoint="https://synthetic-foundry.example.test/api/projects/formapp",
        foundry_agent_name="formapp-agent",
        foundry_model="synthetic-model",
    )
    engine = create_async_engine("postgresql+psycopg://synthetic@127.0.0.1:1/formapp")

    gateway = _default_agent_gateway(settings, SystemClock(), engine)

    assert isinstance(gateway, FoundryAgentGateway)
    assert isinstance(gateway._credential, ManagedIdentityCredential)
    asyncio.run(gateway._credential.close())
    asyncio.run(engine.dispose())
